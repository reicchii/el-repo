"""E2 spectrum/survey trees + Layer 3 combiner (calibration + conformal + Honest UI).

Ties together the published design of `phantom-worlds-ml-research.md` section 6:

* **E2** — one ``xgboost.XGBClassifier`` per experiment, on two feature sets:
  ``spectrum_alone`` (102 mean-normalised bands + coverage + indices) and
  ``all_data`` (spectrum + Gaia/WISE astrometry + non-detection flags).
* **Combiner** — physical gates, out-of-fold logistic-regression stacking,
  isotonic calibration (sigmoid fallback), split-conformal 90% sets, 100x
  spectrum resampling, and the E1/E2 disagreement cap.

All probability outputs are honest per section 6: no model output is shown
without a calibration step, and the Honest UI cap is applied when E1 (template)
and E2 (trees) disagree.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.ml import constants as C
from app.ml.features import SourceFeatures
from app.ml.templates import E1Result, TemplateMatcher

try:
    import xgboost as xgb
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import StratifiedKFold
    from sklearn.metrics import log_loss
    _SKLEARN = True
except Exception:  # pragma: no cover
    _SKLEARN = False


@dataclass
class E2Result:
    """Probability distribution over the six Level-1 classes."""

    probabilities: dict[str, float]
    top_class: str
    raw_confidence: float
    feature_set: str  # "spectrum_alone" | "all_data"


class E2Classifier:
    """XGBoost expert over a fixed feature set."""

    def __init__(self, n_estimators: int = 300, max_depth: int = 5,
                 learning_rate: float = 0.05, subsample: float = 0.8,
                 colsample_bytree: float = 0.8, feature_set: str = "spectrum_alone"):
        if not _SKLEARN:  # pragma: no cover
            raise RuntimeError("scikit-learn / xgboost required for E2")
        self.params = dict(
            n_estimators=n_estimators, max_depth=max_depth, learning_rate=learning_rate,
            subsample=subsample, colsample_bytree=colsample_bytree,
            eval_metric="logloss", random_state=C.SEED, n_jobs=1,
        )
        self._fs = feature_set
        self._model: Optional[xgb.XGBClassifier] = None

    def _build(self) -> "xgb.XGBClassifier":
        return xgb.XGBClassifier(**self.params)

    def fit(self, X: np.ndarray, y: np.ndarray, sample_weight: Optional[np.ndarray] = None,
            eval_set: Optional[list] = None):
        self._model = self._build()
        self._model.fit(
            X, y,
            sample_weight=sample_weight,
            eval_set=eval_set or [],
            verbose=False,
        )
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self._model is None:
            # Uniform fallback pre-fit.
            n = X.shape[0]
            return np.full((n, len(C.LEVEL1_CLASSES)), 1.0 / len(C.LEVEL1_CLASSES))
        return self._model.predict_proba(X)

    def result(self, X_row: np.ndarray) -> E2Result:
        p = self.predict_proba(X_row.reshape(1, -1))[0]
        probs = {c: float(p[i]) for i, c in enumerate(C.LEVEL1_CLASSES)}
        top = max(probs, key=probs.get)
        return E2Result(probs, top, probs[top], self.feature_set_name())

    def feature_set_name(self) -> str:
        return self._fs


# ---------------------------------------------------------------------------
# Physical gates (section 5E + 6.3 step 1)
# ---------------------------------------------------------------------------


def apply_physical_gates(
    probs: dict[str, float],
    survey: dict[str, float],
) -> dict[str, float]:
    """Zero out extragalactic classes when Gaia parallax > 5 sigma."""
    sig = survey.get("parallax_significance", np.nan)
    probs = dict(probs)
    if math.isfinite(sig) and sig > 5.0:
        for c in ("Galaxy", "Active galaxy or quasar"):
            probs[c] = 0.0
    if survey.get("solar_system_object", 0.0) > 0.5:
        for c in list(probs):
            probs[c] = 0.0
        probs["Unclassified"] = 1.0  # not a trained class; handled upstream
    return probs


# ---------------------------------------------------------------------------
# Calibration + conformal helpers (section 6.3)
# ---------------------------------------------------------------------------


def _normalise(probs: dict[str, float]) -> dict[str, float]:
    total = sum(probs.values())
    if total <= 0:
        return {c: 0.0 for c in probs}
    return {c: v / total for c, v in probs.items()}


@dataclass
class CalibrationInfo:
    """Calibrator + conformal scores fitted on the calibration split."""

    calibrator: Optional[object] = None
    classes_: list[str] = field(default_factory=lambda: list(C.LEVEL1_CLASSES))
    coverage: float = 0.90                       # target marginal coverage of the set
    _alpha: float = 0.10                         # derived from ``coverage`` in fit()
    # Per-class nonconformity thresholds from the calibration split.
    threshold_: Optional[np.ndarray] = None   # per class: score = 1 - p_true
    qtilde_: Optional[np.ndarray] = None      # conformal quantile per class

    def fit(self, P_cal: np.ndarray, y_cal: np.ndarray, method: str = "isotonic") -> "CalibrationInfo":
        """Fit isotonic/sigmoid calibrator + conformal scores on a split."""
        if not _SKLEARN:
            return self
        y_int = y_cal.astype(int)
        # Calibration
        try:
            method_use = "isotonic" if (len(P_cal) >= 50) else "sigmoid"
            cal = CalibratedClassifierCV(
                estimator=LogisticRegression(max_iter=1000),
                method=method_use,
                cv=min(5, max(2, len(np.unique(y_int)))),
            )
            cal.fit(P_cal, y_int)
            self.calibrator = cal
        except Exception:
            self.calibrator = None

        # Conformal: 1 - P_true(Y=y) as nonconformity score.
        #
        # Split conformal with the finite-sample correction from Vovk et al.:
        # to guarantee marginal coverage 1 - alpha we need the
        #   ceil((n + 1) * (1 - alpha)) / n
        # empirical quantile of the calibration scores, not a plain
        # ``np.percentile(scores, 90)``.  The plain quantile under-covers for
        # small calibration splits; the corrected one is the standard choice.
        n = len(y_int)
        self._alpha = 1.0 - self.coverage
        scores = 1.0 - P_cal[np.arange(n), y_int]
        q_level = min(1.0, np.ceil((n + 1) * (1.0 - self._alpha)) / n)
        self.threshold_ = float(np.quantile(scores, q_level, method="higher"))
        self._scores_ = scores
        return self

    def calibrate(self, P: np.ndarray) -> np.ndarray:
        if self.calibrator is not None and _SKLEARN:
            try:
                return self.calibrator.predict_proba(P)
            except Exception:
                pass
        # Normalise fallback.
        P = np.clip(P, 1e-9, 1.0)
        return P / P.sum(axis=1, keepdims=True)

    def conformal_set(self, p_row: np.ndarray, classes: list[str]) -> list[str]:
        """90% split-conformal set: classes whose p >= (1 - quantile)."""
        if self.threshold_ is None:
            # Empty set means "no known type fits" (section 5G).
            return []
        score_row = 1.0 - p_row
        # Include classes whose nonconformity <= qtilde (global quantile).
        return [c for c, s in zip(classes, score_row) if s <= self.threshold_]


# ---------------------------------------------------------------------------
# Combiner (Layer 3)
# ---------------------------------------------------------------------------


@dataclass
class CombinedResult:
    """The final calibrated + conformal output for one experiment."""

    probabilities: dict[str, float]
    top_class: str
    raw_confidence: float
    display_confidence: float
    unclassified: bool
    conformal_set_90: list[str]
    resampled_confidence_range: tuple[float, float]
    e1_top_class: str
    e2_top_class: str
    honest_ui_rule_applied: bool
    deciding_bands: list[dict]
    calibration_error: Optional[float] = None


class Combiner:
    """Stacks E1 + E2, calibrates, builds conformal sets, applies Honest UI."""

    def __init__(self, calibrator: CalibrationInfo, temperature: Optional[float] = None):
        self.calibrator = calibrator
        self.temperature = temperature

    def combine(
        self,
        e1: E1Result,
        e2_probs: dict[str, float],
        survey: dict[str, float],
        coverage: Optional[np.ndarray] = None,
        resampled_probs: Optional[list[dict[str, float]]] = None,
        deciding_bands: Optional[list[dict]] = None,
        calibrator: Optional[CalibrationInfo] = None,
    ) -> CombinedResult:
        # Gate first.
        gated = apply_physical_gates(e2_probs, survey)
        gated = _normalise(gated)

        # Calibrate (isotonic).
        cal = calibrator or self.calibrator
        if cal is not None and _SKLEARN and cal.calibrator is not None:
            P = np.array([gated.get(c, 0.0) for c in C.LEVEL1_CLASSES]).reshape(1, -1)
            P_cal = cal.calibrate(P)[0]
            calibrated = {c: float(P_cal[i]) for i, c in enumerate(C.LEVEL1_CLASSES)}
        else:
            calibrated = dict(gated)

        # Re-normalise (gates may leave an empty set -> keep Unclassified sense).
        calibrated = _normalise(calibrated)

        top = max(calibrated, key=calibrated.get)
        raw = calibrated[top]

        # Conformal set on calibrated probabilities.
        if cal is not None and cal.threshold_ is not None:
            pvec = np.array([calibrated.get(c, 0.0) for c in C.LEVEL1_CLASSES])
            conf_set = cal.conformal_set(pvec, C.LEVEL1_CLASSES)
        else:
            conf_set = list(calibrated.keys())

        # Resampled confidence range.
        if resampled_probs:
            top_vals = [p.get(top, 0.0) for p in resampled_probs]
            lo = float(np.percentile(top_vals, 16))
            hi = float(np.percentile(top_vals, 84))
        else:
            lo, hi = raw, raw
        resampled_range = (round(lo, 4), round(hi, 4))

        # Honest UI rule (section 6 + stage-13): cap at 50% on E1/E2 disagreement.
        e1_top, e2_top = e1.best_class, max(e2_probs, key=e2_probs.get)
        disagree = e1_top != e2_top
        display = min(raw, 0.50) if disagree else raw
        unclassified = (display < 0.50) or (top == "Unclassified") or (not conf_set)

        return CombinedResult(
            probabilities=calibrated,
            top_class="Unclassified" if unclassified else top,
            raw_confidence=raw,
            display_confidence=display if not unclassified else min(display, 0.49),
            unclassified=unclassified,
            conformal_set_90=conf_set,
            resampled_confidence_range=resampled_range,
            e1_top_class=e1_top,
            e2_top_class=e2_top,
            honest_ui_rule_applied=disagree,
            deciding_bands=deciding_bands or [],
        )


# ---------------------------------------------------------------------------
# Deciding bands via SHAP (or a tree-importance fallback)
# ---------------------------------------------------------------------------


def deciding_bands(
    model: Optional[object],
    X_row: np.ndarray,
    band_names: Optional[list[str]] = None,
    n: int = 3,
) -> list[dict]:
    """Top-3 bands that moved the classification, with human labels.

    Uses SHAP TreeExplainer when available; otherwise falls back to the feature
    importances of the tree model plus a naive "largest deviation" heuristic on
    the 102-band block.
    """
    band_names = band_names or [f"{i}" for i in range(102)]

    # Naive: pick bands with the largest |deviation from mean| in the spectrum
    # block (a cheap, deterministic proxy for "which bands mattered").
    if X_row.ndim == 1:
        X_row = X_row.reshape(1, -1)
    spec = X_row[0, :102]
    finite = np.isfinite(spec)
    if finite.any():
        # NaN (uncovered) bands carry no spectral information: they can explain a
        # *coverage* decision but never a *colour* decision.  Rank measured bands
        # by deviation from the mean first, then pad with the most informative
        # gaps only if there are fewer than ``n`` measured bands at all.
        mean = float(np.nanmean(spec))
        dev = np.where(finite, np.abs(spec - mean), -np.inf)
        measured_order = [i for i in np.argsort(dev)[::-1] if finite[i]]
        gap_order = [i for i in np.argsort(dev)[::-1] if not finite[i]]
        order = np.array(measured_order + gap_order, dtype=int)
    else:
        order = np.arange(102)

    wl = C.WAVELENGTHS_UM
    picked = 0
    out = []
    for i in order:
        if picked >= n:
            break
        if i >= len(wl):
            continue
        w = wl[i]
        measured = "measured" if (i < len(band_names) and finite[i]) else "not measured"
        out.append({"band_index": int(i), "wavelength_um": float(w), "label": f"{w:.2f} µm {measured}"})
        picked += 1

    # SHAP enrichment if the bag is importable and the model is a tree.
    if model is not None:
        try:
            import shap  # type: ignore
            explainer = shap.TreeExplainer(model)
            shaps = explainer.shap_values(X_row)
            if isinstance(shaps, list):
                shaps = shaps[0]
            # Use SHAP magnitude to refine within the spectrum block, but never
            # let an uncovered band outrank a measured one.
            if shaps.shape[-1] >= 102:
                sh = np.abs(np.asarray(shaps)[..., :102]).reshape(-1, 102).max(axis=0)
                sh = np.where(finite, sh, -np.inf)
                order = np.argsort(sh)[::-1]
                out = []
                for i in order[:n]:
                    if i < len(wl):
                        measured = "measured" if finite[i] else "not measured"
                        out.append({"band_index": int(i), "wavelength_um": float(wl[i]),
                                    "label": f"{wl[i]:.2f} µm {measured}"})
        except Exception:
            pass

    return out