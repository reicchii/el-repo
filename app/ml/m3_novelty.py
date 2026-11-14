"""M3 — novelty / anomaly detector + discovery ontology assignment.

Screens ordinary contamination first (section 5G), then combines the template
reduced-chi-square (threshold 3, 10% error floor), an empty 90% conformal set
and an ``IsolationForest`` (section 13.1) into a calibrated
``novelty_percentile`` and a Discovery Ontology label (U1..U4).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.ml import constants as C
from app.ml.dataset import SyntheticDataset
from app.ml.features import SourceFeatures
from app.ml.templates import E1Result

try:
    from sklearn.ensemble import IsolationForest
    _SKLEARN = True
except Exception:  # pragma: no cover
    _SKLEARN = False


@dataclass
class ContaminationScreen:
    """Which ordinary-cause screen triggered (section 5G order)."""

    passed: bool = True
    triggered: Optional[str] = None

    @classmethod
    def evaluate(cls, readings, astrometry=None) -> "ContaminationScreen":
        # blend share first
        if readings.blend_share > 0.3:
            return cls(False, "blend_share > 0.3")
        # variability
        if readings.variable_flag:
            return cls(False, "visit-to-visit variability")
        # overflow / ghost flags anywhere in the spectrum
        for b in readings.spectral_bands:
            if (b.flag or "") in {"overflow", "overflow_suspected", "ghost", "blend"}:
                return cls(False, f"detector flag: {b.flag}")
        return cls(True, None)


@dataclass
class NoveltyVerdict:
    """M3's output for one source."""

    novelty_percentile: float          # 0..100, calibrated against train set
    is_novel: bool
    discovery_class: str               # U1..U4
    reasons: list[str] = field(default_factory=list)
    screen: Optional[str] = None       # contamination screen that triggered, if any
    reduced_chi2: Optional[float] = None
    isolation_score: Optional[float] = None
    conformal_empty: bool = False


class NoveltyDetector:
    """Combine reduced chi2 + conformal + isolation forest."""

    def __init__(self, error_floor: float = 0.10, chi2_threshold: float = 3.0):
        self.error_floor = error_floor
        self.chi2_threshold = chi2_threshold
        self._iso: Optional[object] = None
        self._train_scores: Optional[np.ndarray] = None  # for percentile calibration

    def fit(self, dataset: SyntheticDataset, split_name: str = "train") -> "NoveltyDetector":
        if not _SKLEARN:
            return self
        idx = dataset.split_indices()[split_name]
        X, _, _ = _dataset_feature_matrix(dataset, idx)
        self._iso = IsolationForest(n_estimators=200, contamination=0.1, random_state=C.SEED, n_jobs=1)
        self._iso.fit(X)
        self._train_scores = self._iso.score_samples(X)
        return self

    def _iso_score(self, X_row: np.ndarray) -> Optional[float]:
        if self._iso is None:
            return None
        return float(self._iso.score_samples(X_row.reshape(1, -1))[0])

    def _percentile(self, score: Optional[float]) -> Optional[float]:
        if score is None or self._train_scores is None:
            return None
        # Higher isolation score = more normal.  Novelty percentile is the
        # fraction of the training distribution that is *more* normal than this.
        return float((self._train_scores >= score).mean() * 100.0)

    def evaluate(
        self,
        readings,
        e1: Optional[E1Result] = None,
        conformal_empty: bool = False,
        feats: Optional[SourceFeatures] = None,
        survey: Optional[dict[str, float]] = None,
        astrometry=None,
    ) -> NoveltyVerdict:
        screen = ContaminationScreen.evaluate(readings, astrometry)

        # If an ordinary cause screted, that is the whole story.
        if not screen.passed:
            return NoveltyVerdict(
                novelty_percentile=0.0, is_novel=False,
                discovery_class="U3",  # wrong label / contaminated
                reasons=[f"Ordinary contamination: {screen.triggered}"],
                screen=screen.triggered,
            )

        reasons: list[str] = []
        reduced_chi2 = e1.template.reduced_chi2 if e1 is not None else None

        # chi2 gate.
        chi2_flag = reduced_chi2 is not None and np.isfinite(reduced_chi2) and reduced_chi2 > self.chi2_threshold
        if chi2_flag:
            reasons.append(f"template reduced chi2 {reduced_chi2:.2f} > {self.chi2_threshold}")

        # conformal gate.
        if conformal_empty:
            reasons.append("empty 90% conformal set")
        conformal_flag = conformal_empty

        # isolation forest.
        iso_score = None
        if feats is not None:
            iso_score = self._iso_score(feats.spectrum_vector_full())
        iso_pct = self._percentile(iso_score)
        iso_flag = iso_pct is not None and iso_pct < 10.0  # bottom decile = unusual
        if iso_flag:
            reasons.append(f"isolation-forest novelty percentile {iso_pct:.1f}")

        # Combined novelty percentile: min across the three signals (the most
        # conservative).  When any hard gate fires, pull it toward zero.
        parts = []
        if chi2_flag:
            parts.append(10.0)
        if conformal_flag:
            parts.append(10.0)
        if iso_pct is not None:
            parts.append(max(0.0, min(100.0, iso_pct)))
        novelty = min(parts) if parts else 100.0
        is_novel = chi2_flag or conformal_flag or iso_flag

        disc = self._assign_discovery(readings, survey, is_novel, reasons, astrometry)
        return NoveltyVerdict(
            novelty_percentile=round(novelty, 1),
            is_novel=is_novel,
            discovery_class=disc,
            reasons=reasons,
            reduced_chi2=round(reduced_chi2, 3) if reduced_chi2 is not None and np.isfinite(reduced_chi2) else None,
            isolation_score=iso_score,
            conformal_empty=conformal_empty,
        )

    def _assign_discovery(self, readings, survey, is_novel, reasons, astrometry) -> str:
        # U1: no Gaia optical counterpart (uncatalogued in optical surveys).
        g = readings.gaia
        no_optical = g is None or (g.source_id is None and g.parallax_mas is None)
        if no_optical:
            return "U1"

        # U4: visit-to-visit variability not explained by existing taxa.
        if readings.variable_flag and is_novel:
            return "U4"

        # U2: untyped dot (spectrum-only, unclassified).
        if is_novel:
            return "U2"

        # U3: wrong label (model name disagrees with a known catalogue type).
        if survey is not None and survey.get("simbad_has_type", 0.0) >= 0.5 and is_novel:
            return "U3"

        # Default: not novel -> the object fits a known type; M3 does not add a
        # discovery class.  (The type panel drives the story.)
        return "U2"


def _dataset_feature_matrix(dataset: SyntheticDataset, idx: np.ndarray):
    """Build source features from synthetic spectra (mirrors pipeline)."""
    from app.ml.pipeline import _features_from_arrays

    rows = []
    for i in idx:
        feats = _features_from_arrays(dataset.spectra[i], dataset.errors[i], dataset.covered[i])
        rows.append(feats.spectrum_vector_full())
    X = np.array(rows, dtype=float)
    y = dataset.y[idx]
    w = dataset.weight[idx]
    return X, y, w


def train_default() -> NoveltyDetector:
    from app.ml.dataset import generate_dataset

    det = NoveltyDetector()
    det.fit(generate_dataset())
    return det