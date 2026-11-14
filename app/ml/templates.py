"""E1 — template matcher (pure numpy, SPIFF-style reduced chi-square).

Implements `phantom-worlds-ml-research.md` sections 5C and 13.1:

* analytic scale solver (the normal-equation scale that minimises χ² between
  the observed spectrum and a mean-normalised template),
* reduced chi-square with an optional error floor,
* drop-the-worst-5-bands iteration (the SPIFF method),
* top-3 templates + per-band residuals + an ultracool-dwarf subtype estimate.

No training: the matcher is fed template dictionaries from
``app.ml.dataset.SyntheticDataset``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.ml import constants as C


@dataclass
class TemplateMatch:
    """One template's fit result."""

    name: str
    scale: float
    reduced_chi2: float
    chi2: float
    n_bands_used: int
    residuals: np.ndarray  # per-band (obs - model), NaN where unused
    is_subtype: bool = False


@dataclass
class E1Result:
    """Top-3 template matches + residuals + subtype estimate."""

    template: TemplateMatch
    runner_up: list[TemplateMatch]
    subtype_estimate: Optional[str]
    subtype_distance: Optional[float]  # ordinal distance to nearest subtype
    per_band_residuals: np.ndarray  # residual of the best class template

    @property
    def best_class(self) -> str:
        return self.template.name


class TemplateMatcher:
    """Emit the reduced-chi-square fit of one spectrum against templates."""

    def __init__(self, error_floor: float = 0.10, drop_worst: int = 5):
        self.error_floor = error_floor
        self.drop_worst = drop_worst

    # -- core fit ------------------------------------------------------------

    def fit_template(
        self,
        flux: np.ndarray,
        err: np.ndarray,
        template: np.ndarray,
    ) -> TemplateMatch:
        """Analytic scale + reduced chi2, dropping the ``drop_worst`` bands."""
        flux = np.asarray(flux, dtype=float)
        err = np.asarray(err, dtype=float)
        template = np.asarray(template, dtype=float)

        # Valid bands: finite flux/err and a positive template value.
        valid = (
            np.isfinite(flux)
            & np.isfinite(err)
            & np.isfinite(template)
            & (template > 0)
            & (err > 0)
        )
        if valid.sum() < 8:
            return TemplateMatch("", np.nan, np.inf, np.inf, 0,
                                 np.full_like(flux, np.nan))

        err_valid = np.where(valid, err, np.inf)
        # 10% error floor (section 5G).
        med_flux = np.nanmedian(np.abs(flux))
        err_floor = self.error_floor * (med_flux if med_flux > 0 else 1.0)
        err_used = np.maximum(err_valid, err_floor)

        f = np.where(valid, flux, 0.0)
        t = np.where(valid, template, 0.0)
        w = 1.0 / (err_used * err_used)

        return self._fit_with_drops(f, t, w, valid)

    def _fit_with_drops(self, f, t, w, valid) -> TemplateMatch:
        mask = valid.copy()
        scale = np.nan
        residuals = np.full_like(f, np.nan)
        n_used = 0
        chi2 = np.inf

        # Iterate a few times: fit, then drop the top-5 |residual| bands.
        for _ in range(self.drop_worst + 1):
            fm = f[mask]
            tm = t[mask]
            if tm.size >= 8:
                with np.errstate(divide="ignore", invalid="ignore"):
                    wm = w[mask]
                    denom = (tm * tm * wm).sum()
                    num = (fm * tm * wm).sum()
                    s = num / denom if denom > 0 else np.nan
                if np.isfinite(s) and s > 0:
                    resid = (fm - s * tm) * np.sqrt(wm)
                    c2 = float((resid * resid).sum())
                    if c2 < chi2 and tm.size > 5:
                        scale = float(s)
                        chi2 = c2
                        n_used = int(tm.size)
                        full_resid = np.full_like(f, np.nan)
                        full_resid[mask] = fm - s * tm
                        residuals = full_resid

            # Drop the worst 5 used bands by |residual| and refit.
            if mask.sum() <= 8:
                break
            resid_a = np.abs(residuals)
            resid_a[~mask] = -np.inf
            worst = np.argsort(resid_a[mask])[::-1][: self.drop_worst]
            idx = np.where(mask)[0][worst]
            mask = mask.copy()
            mask[idx] = False

        reduced = (chi2 / (n_used - 1)) if n_used > 1 else np.inf
        return TemplateMatch("", scale, reduced, chi2, n_used, residuals)

    # -- entrypoint ----------------------------------------------------------

    def match(
        self,
        flux: np.ndarray,
        err: np.ndarray,
        class_templates: dict[str, np.ndarray],
        subtype_templates: Optional[dict[str, np.ndarray]] = None,
        top_k: int = 3,
    ) -> E1Result:
        # Match the class templates.
        class_matches = {
            name: self.fit_template(flux, err, tmpl)
            for name, tmpl in class_templates.items()
        }
        ordered = sorted(
            class_matches.values(),
            key=lambda m: (m.reduced_chi2, m.chi2),
        )
        top = ordered[:top_k]

        if not top:
            raise ValueError("no templates supplied to E1")

        # Subtype estimate (ultracool dwarfs only).
        subtype_estimate: Optional[str] = None
        subtype_distance: Optional[float] = None
        best_subtype_fit = np.inf
        best_subtype = None
        if subtype_templates:
            for sub, tmpl in subtype_templates.items():
                m = self.fit_template(flux, err, tmpl)
                if m.reduced_chi2 < best_subtype_fit:
                    best_subtype_fit = m.reduced_chi2
                    best_subtype = sub
            if best_subtype is not None:
                subtype_estimate = best_subtype
                subtype_distance = 0.0  # ordinal distance == 0 by definition

        # Attach names to the class matches.
        top_named = []
        for m in top:
            name = next((n for n, mm in class_matches.items() if mm is m), "")
            top_named.append(
                TemplateMatch(name, m.scale, m.reduced_chi2, m.chi2, m.n_bands_used, m.residuals)
            )

        return E1Result(
            template=top_named[0],
            runner_up=top_named[1:],
            subtype_estimate=subtype_estimate,
            subtype_distance=subtype_distance,
            per_band_residuals=top_named[0].residuals,
        )

    @property
    def best_class(self) -> str:  # convenience for the combiner
        return self.match_result.template.name if getattr(self, "match_result", None) else ""

    # helper for the combiner
    def top_class_name(self, flux, err, class_templates) -> str:
        res = self.match(flux, err, class_templates, top_k=1)
        return res.best_class