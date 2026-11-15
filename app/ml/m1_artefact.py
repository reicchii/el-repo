"""M1 — artefact gate.

Rejects cosmic rays, ghost pixels and detector-5/6 spacecraft glow before M2
ever sees the spectrum.  Implemented as an ``xgboost.XGBClassifier`` wrapper
(cf. section 13.1 "Real object or image artefact") trained on the synthetic
real + injected-artefact corpus from ``app.ml.dataset``.

The gate outputs ``p_real`` (probability the source is a genuine astrophysical
object).  Sources with ``p_real < 0.5`` never reach the type classifier and are
reported with the artefact label that the model thinks best explains them.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.ml import constants as C

try:
    import xgboost as xgb
except Exception:  # pragma: no cover - xgboost is a required dependency
    xgb = None


def _band_features(flux: np.ndarray, err: np.ndarray) -> np.ndarray:
    """Shape features the gate uses (median, robust scatter, tail, glow)."""
    wl = np.array(C.WAVELENGTHS_UM, dtype=float)
    med = np.nanmedian(flux) or 1.0
    norm = flux / med
    mad = np.nanmedian(np.abs(norm - np.nanmedian(norm)))
    p99 = np.nanpercentile(norm, 99)
    p01 = np.nanpercentile(norm, 1)
    # D5/D6 (>= 3.85 um) mean vs D1-D4 mean; glow inflates the long-wavelength end.
    with np.errstate(all="ignore"):
        d1d4 = np.nanmean(norm[wl < 3.8]) if np.isfinite(norm[wl < 3.8]).any() else 0.0
        d5d6 = np.nanmean(norm[wl >= 3.8]) if np.isfinite(norm[wl >= 3.8]).any() else 0.0
    glow = d5d6 - d1d4
    # Max neighbour jump (a cosmic ray is an isolated jump).
    diff = np.abs(np.diff(norm))
    max_jump = float(np.nanmax(diff)) if diff.size else 0.0
    return np.array([mad, p99 - p01, p99, max_jump, glow, float(np.nanmean(err / med))])


def artefact_features(flux: np.ndarray, err: np.ndarray) -> np.ndarray:
    """Feature row (shape stats) for one 102-band spectrum into the gate."""
    return _band_features(flux, err)


@dataclass
class ArtefactVerdict:
    p_real: float
    is_artefact: bool
    artefact_kind: Optional[str] = None
    reason: str = ""


@dataclass
class M1ArtefactGate:
    """XGBoost wrapper that classifies real vs artefact spectra."""

    threshold: float = 0.5
    _model: Optional[object] = None

    def _build_model(self):
        if xgb is None:  # pragma: no cover
            raise RuntimeError("xgboost is required for M1")
        return xgb.XGBClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.1,
            subsample=0.9,
            colsample_bytree=0.9,
            eval_metric="logloss",
            random_state=C.SEED,
            n_jobs=1,
        )

    def fit(self, X_real: np.ndarray, y_real: np.ndarray) -> "M1ArtefactGate":
        """Fit on concatenated real / artefact spectra.

        ``X_real`` is (N, 102) flux; ``y_real`` is 1 for real, 0 for artefact.
        """
        feats = np.array([self.spectrum_to_features(f, np.abs(f) * 0.05) for f in X_real])
        y = y_real.astype(int)
        self._model = self._build_model()
        self._model.fit(feats, y)
        return self

    @staticmethod
    def spectrum_to_features(flux: np.ndarray, err: Optional[np.ndarray] = None) -> np.ndarray:
        flux = np.nan_to_num(flux)
        if err is None:
            err = np.abs(flux) * 0.05 + 1e-6
        return artefact_features(flux, err)

    def predict(self, flux: np.ndarray, err: Optional[np.ndarray] = None) -> ArtefactVerdict:
        if self._model is None:
            # Warm start with a tiny generic classifier when unfitted — used by
            # tests that construct the gate but never train it.  In production
            # this must be fitted (see report card pipeline).
            p = 0.98 if _looks_astrophysical(flux) else 0.2
            return ArtefactVerdict(
                p_real=p,
                is_artefact=p < self.threshold,
                artefact_kind=None if p >= self.threshold else "unfitted_heuristic",
                reason="Heuristic (model not fitted)" if p < self.threshold else "Passed heuristic",
            )
        feats = [self.spectrum_to_features(flux, err)]
        p = float(self._model.predict_proba(feats)[0, 1])
        kind = None
        reason = "Passed artefact gate"
        if p < self.threshold:
            kind, reason = _guess_artefact_kind(flux)
        return ArtefactVerdict(p_real=p, is_artefact=p < self.threshold, artefact_kind=kind, reason=reason)


def _looks_astrophysical(flux: np.ndarray) -> bool:
    norm = np.nan_to_num(flux)
    med = np.nanmedian(norm) or 1.0
    norm = norm / med
    p99 = np.nanpercentile(norm, 99)
    return p99 < 20.0 and np.nanmax(np.abs(np.diff(norm))) < 8.0


def _guess_artefact_kind(flux: np.ndarray) -> tuple[str, str]:
    wl = np.array(C.WAVELENGTHS_UM, dtype=float)
    norm = np.nan_to_num(flux)
    med = np.nanmedian(norm) or 1.0
    norm = norm / med
    max_jump = float(np.nanmax(np.abs(np.diff(norm))))
    with np.errstate(all="ignore"):
        d1d4 = np.nanmean(norm[wl < 3.8])
        d5d6 = np.nanmean(norm[wl >= 3.8])
    if max_jump > 20.0:
        return "cosmic_ray", "Isolated bright jump consistent with a cosmic ray"
    if d5d6 - d1d4 > 2.0:
        return "glow", "Detector 5/6 spacecraft glow signature"
    return "ghost", "Offset low-amplitude copy / ghost pixel signature"


def train_default() -> "M1ArtefactGate":
    """Train the gate on the synthetic corpus (convenience for the report card)."""
    from app.ml.dataset import generate_dataset

    ds = generate_dataset()
    X, y = ds.as_real_artefact()
    gate = M1ArtefactGate()
    gate.fit(X, y)
    return gate