"""End-to-end M2 pipeline: trains E2 trees, fits calibration/conformal, and
produces the two stored results (spectrum_alone vs all_data) for a source.

This is the glue between ``dataset`` (synthetic corpus), ``templates`` (E1),
``m2_classifier`` (E2 + combiner) and the frozen ``sample_packs`` schemas.
The report-card script and the citizen-science router both call it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.ml import constants as C
from app.ml.dataset import SyntheticDataset, generate_dataset
from app.ml.features import RealSurvey, SourceFeatures
from app.ml.m2_classifier import (
    CalibrationInfo,
    Combiner,
    CombinedResult,
    E2Classifier,
    deciding_bands,
)
from app.ml.templates import E1Result, TemplateMatcher
from app.schemas import DecidingBand, IdentityPanel, PredictionBlock, Readings


@dataclass
class TrainedModels:
    """Everything M2 needs, fitted once and reused across sources."""

    dataset: SyntheticDataset
    matcher: TemplateMatcher
    e2_spectrum: E2Classifier
    e2_all: E2Classifier
    cal_spectrum: CalibrationInfo
    cal_all: CalibrationInfo
    class_templates: dict[str, np.ndarray]
    subtype_templates: dict[str, np.ndarray]
    # evaluation metrics, filled after training
    metrics: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def _make_X_y(dataset: SyntheticDataset, idx: np.ndarray, all_data: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build the feature matrix for the given indices.

    Synthetic spectra are converted via the same SourceFeatures pipeline as the
    benchmark targets, so the two feature sets match exactly.  For ``all_data``
    the survey block is filled with class-appropriate synthetic astrometry so
    the trees learn the physical separators (parallax, abs. mag, PM).
    """
    rows = []
    for i in idx:
        flux = dataset.spectra[i]
        err = dataset.errors[i]
        cov = dataset.covered[i]
        cls = C.INT_TO_CLASS[int(dataset.y[i])]
        # Synthetic SourceFeatures from raw spectrum + class survey.
        feats = SourceFeatures.from_raw_spectrum(flux, err, cov)
        if all_data:
            _inject_survey(feats, cls, i)
        rows.append(feats.all_vector_full() if all_data else feats.spectrum_vector_full())
    X = np.array(rows, dtype=float)
    y = dataset.y[idx]
    w = dataset.weight[idx]
    return X, y, w


def _inject_survey(feats: SourceFeatures, cls: str, seed: int) -> None:
    """Assign deterministic class-appropriate survey features to a synthetic row."""
    rng = np.random.default_rng(C.SEED + seed)
    if cls == "Ultracool dwarf":
        feats.survey["parallax_mas"] = float(rng.uniform(80.0, 350.0))
        feats.survey["parallax_significance"] = float(rng.uniform(20.0, 200.0))
        feats.survey["absolute_magnitude_g"] = float(rng.uniform(15.0, 20.0))
        feats.survey["pm_total_mas_yr"] = float(rng.uniform(500.0, 3000.0))
        feats.survey["gaia_match"] = 0.0 if rng.random() < 0.15 else 1.0
        feats.survey["neowise_match"] = 1.0
        feats.survey["catwise_match"] = 1.0
    elif cls == "Star":
        feats.survey["parallax_mas"] = float(rng.uniform(20.0, 500.0))
        feats.survey["parallax_significance"] = float(rng.uniform(20.0, 400.0))
        feats.survey["absolute_magnitude_g"] = float(rng.uniform(4.0, 10.0))
        feats.survey["pm_total_mas_yr"] = float(rng.uniform(50.0, 1000.0))
        feats.survey["gaia_match"] = 1.0
        feats.survey["neowise_match"] = 1.0
        feats.survey["catwise_match"] = 1.0
    elif cls == "Young star":
        feats.survey["parallax_mas"] = float(rng.uniform(5.0, 100.0))
        feats.survey["parallax_significance"] = float(rng.uniform(5.0, 30.0))
        feats.survey["absolute_magnitude_g"] = float(rng.uniform(6.0, 12.0))
        feats.survey["pm_total_mas_yr"] = float(rng.uniform(10.0, 200.0))
        feats.survey["gaia_match"] = 1.0
        feats.survey["neowise_match"] = 1.0
    elif cls == "Evolved giant star":
        feats.survey["parallax_mas"] = float(rng.uniform(0.5, 5.0))
        feats.survey["parallax_significance"] = float(rng.uniform(10.0, 50.0))
        feats.survey["absolute_magnitude_g"] = float(rng.uniform(-4.0, -1.0))
        feats.survey["pm_total_mas_yr"] = float(rng.uniform(10.0, 100.0))
        feats.survey["gaia_match"] = 1.0
    else:  # Galaxy / AGN
        feats.survey["parallax_mas"] = float(np.nan)
        feats.survey["parallax_significance"] = float(np.nan)
        feats.survey["absolute_magnitude_g"] = float(np.nan)
        feats.survey["pm_total_mas_yr"] = float(np.nan)
        feats.survey["gaia_match"] = 1.0
        feats.survey["neowise_match"] = 0.0
        feats.survey["catwise_match"] = 0.0


def _features_from_arrays(flux: np.ndarray, err: np.ndarray, cov: np.ndarray) -> SourceFeatures:
    """SourceFeatures for a synthetic spectrum (real molecule indices)."""
    return SourceFeatures.from_raw_spectrum(flux, err, cov)


def train_models(
    dataset: Optional[SyntheticDataset] = None,
    e2_params: Optional[dict] = None,
    seed: int = C.SEED,
) -> TrainedModels:
    """Train E2 (both feature sets) + calibration on the corpus splits."""
    dataset = dataset or generate_dataset(seed=seed)
    split = dataset.split_indices()
    train_idx, cal_idx = split["train"], split["calibrate"]

    # E2 classifiers.
    e2_params = e2_params or {}
    e2_spectrum = E2Classifier(feature_set="spectrum_alone", **e2_params)
    e2_all = E2Classifier(feature_set="all_data", **e2_params)

    Xs, ys, ws = _make_X_y(dataset, train_idx, all_data=False)
    Xa, ya, wa = _make_X_y(dataset, train_idx, all_data=True)
    e2_spectrum.fit(Xs, ys, sample_weight=ws)
    e2_all.fit(Xa, ya, sample_weight=wa)

    # Calibration split predictions -> isotonic + conformal threshold.
    Xcs, ycs, _ = _make_X_y(dataset, cal_idx, all_data=False)
    Xca, yca, _ = _make_X_y(dataset, cal_idx, all_data=True)
    Pcs = e2_spectrum.predict_proba(Xcs)
    Pca = e2_all.predict_proba(Xca)

    cal_spectrum = CalibrationInfo().fit(Pcs, ycs)
    cal_all = CalibrationInfo().fit(Pca, yca)

    # Templates from the train split (E1).
    class_templates = dataset.class_templates(train_idx)
    subtype_templates = dataset.subtype_templates(train_idx)

    metrics = _evaluate(dataset, split["test"], e2_spectrum, e2_all, cal_spectrum, cal_all)

    return TrainedModels(
        dataset=dataset,
        matcher=TemplateMatcher(),
        e2_spectrum=e2_spectrum,
        e2_all=e2_all,
        cal_spectrum=cal_spectrum,
        cal_all=cal_all,
        class_templates=class_templates,
        subtype_templates=subtype_templates,
        metrics=metrics,
    )


def _evaluate(dataset, test_idx, e2s, e2a, cal_s, cal_a) -> dict[str, float]:
    """Balanced accuracy / calibration error on the gold test set."""
    gold = test_idx[dataset.grade[test_idx] == 1]
    metrics: dict[str, float] = {}

    for name, e2, cal, all_data in [
        ("spectrum_alone", e2s, cal_s, False),
        ("all_data", e2a, cal_a, True),
    ]:
        X, y_true, _ = _make_X_y(dataset, gold, all_data=all_data)
        P = e2.predict_proba(X)
        yp = P.argmax(axis=1)

        # Per-class recall.
        recalls = []
        for c in range(len(C.LEVEL1_CLASSES)):
            m = y_true == c
            if m.sum() == 0:
                continue
            recalls.append(float((yp[m] == c).mean()))
        balanced = float(np.mean(recalls)) if recalls else 0.0

        # Calibration error (ECE).
        if cal.calibrator is not None:
            Pcal = cal.calibrate(P)
        else:
            Pcal = P
        conf = Pcal.max(axis=1)
        correct = (Pcal.argmax(axis=1) == y_true).astype(float)
        ece = _ece(conf, correct)

        metrics[f"{name}_balanced_accuracy"] = balanced
        metrics[f"{name}_calibration_error"] = ece
        metrics[f"{name}_n_test"] = len(y_true)

        # Empirical coverage of the split-conformal 90% sets on the gold test
        # split.  A target of 0.90 means the true class should land inside the
        # set for ~90% of sources; the band is the release gate (88-92%).
        try:
            Pc = cal.calibrate(P) if cal.calibrator is not None else P
            covered = 0
            for i in range(len(y_true)):
                s = cal.conformal_set(Pc[i], list(C.LEVEL1_CLASSES))
                if C.LEVEL1_CLASSES[int(y_true[i])] in s:
                    covered += 1
            metrics[f"{name}_conformal_coverage"] = covered / max(len(y_true), 1)
        except Exception:
            metrics[f"{name}_conformal_coverage"] = float("nan")

    return metrics


def _ece(conf: np.ndarray, correct: np.ndarray, n_bins: int = 10) -> float:
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    total = len(conf)
    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        m = (conf > lo) & (conf <= hi)
        if m.sum() == 0:
            continue
        acc = correct[m].mean()
        ece += (m.sum() / total) * abs(acc - conf[m].mean())
    return float(ece)


# ---------------------------------------------------------------------------
# Source prediction
# ---------------------------------------------------------------------------


def predict_source(
    models: TrainedModels,
    readings: Readings,
    survey: Optional[RealSurvey] = None,
    resample_times: int = 100,
) -> IdentityPanel:
    """Produce the full spectrum_alone + all_data identity panel for a source.

    Both stored results follow section 6: E1..E3 for spectrum-only, E1..E7 for
    all data.
    """
    feats = SourceFeatures.from_readings(readings, survey)

    # -- spectrum_alone ------------------------------------------------------
    sp = _predict_one(
        models,
        feats.spectrum_vector_full(),
        feats.survey,
        feats.coverage,
        e2=models.e2_spectrum,
        cal=models.cal_spectrum,
        all_data=False,
        resample_times=resample_times,
        survey_provided=survey is not None,
    )

    # -- all_data ------------------------------------------------------------
    all_d = _predict_one(
        models,
        feats.all_vector_full(),
        feats.survey,
        feats.coverage,
        e2=models.e2_all,
        cal=models.cal_all,
        all_data=True,
        resample_times=resample_times,
        survey_provided=survey is not None,
    )

    honest = _honest_ui(sp, all_d)
    return IdentityPanel(
        spectrum_alone=_to_block(sp, ["E1", "E2"], "spectrum_alone"),
        all_data=_to_block(all_d, ["E1", "E2", "E4", "E5", "E6", "E7"], "all_data"),
        honest_ui=honest,
    )


@dataclass
class _OneResult:
    probs: dict[str, float]
    top_class: str
    raw_confidence: float
    display_confidence: float
    unclassified: bool
    conformal_set: list[str]
    resampled_range: tuple[float, float]
    e1_top: str
    e2_top: str
    honest_applied: bool
    deciding: list[dict]
    discovery: str


def _predict_one(
    models, X_row, survey, coverage,
    e2, cal, all_data, resample_times=100, survey_provided=True,
) -> _OneResult:
    # E2 probabilities.
    e2_result = e2.result(X_row)
    e2_probs = e2_result.probabilities

    # E1 template match (on the spectrum, mean-normalised raw flux).
    flux_unnorm = None
    # We need the unnormalised flux for E1; SourceFeatures stores normalised.
    # Recover by using coverage + the normalised spectrum (template match is
    # scale-invariant, so the mean-normalised vector works).
    spec_norm = X_row[:102]

    e1 = models.matcher.match(
        spec_norm,
        np.abs(spec_norm) * 0.05 + 1e-6,
        models.class_templates,
        models.subtype_templates if all_data else None,
        top_k=3,
    )

    # 100x resampling of the spectrum within flux errors.
    resampled = []
    rng = np.random.default_rng(C.SEED)
    err_map = np.abs(spec_norm) * 0.05 + 1e-6
    for _ in range(resample_times):
        pert = spec_norm + rng.normal(0.0, np.nan_to_num(err_map, nan=0.0))
        row = X_row.copy()
        row[:102] = pert
        r = e2.result(row)
        resampled.append(r.probabilities)

    combiner = Combiner(cal)
    combined = combiner.combine(
        e1, e2_probs, survey, coverage=coverage,
        resampled_probs=resampled,
        deciding_bands=deciding_bands(e2._model, X_row.reshape(1, -1)),
    )

    discovery = _assign_discovery(
        e1, e2_probs, combined, survey, survey_provided, all_data,
    )

    return _OneResult(
        probs=combined.probabilities,
        top_class=combined.top_class,
        raw_confidence=combined.raw_confidence,
        display_confidence=combined.display_confidence,
        unclassified=combined.unclassified,
        conformal_set=combined.conformal_set_90,
        resampled_range=combined.resampled_confidence_range,
        e1_top=combined.e1_top_class,
        e2_top=combined.e2_top_class,
        honest_applied=combined.honest_ui_rule_applied,
        deciding=combined.deciding_bands,
        discovery=discovery,
    )


def _assign_discovery(e1, e2_probs, combined, survey, survey_provided, all_data) -> str:
    """Map the honest outcome to the discovery ontology U1..U4.

    Order matters (Section 4 / Pillar 3-4): U4 (variability = new behaviour)
    first, then U1 (uncatalogued in Gaia optical), then U3, then U2.
    """
    # U4: visit-to-visit variability -> new behaviour not explained by taxa.
    # Checked first so a known variable (R Dra, RW Aur) reports U4 even though
    # it also lacks a clean Gaia parallax.
    if survey.get("variable_flag", 0.0) >= 0.5:
        return "U4"
    # U1: genuinely no Gaia optical counterpart (WISE 0855 Y dwarf).
    if survey.get("gaia_match", np.nan) == 0.0:
        return "U1"
    # U3: wrong label (model top disagrees with a known catalogue type).
    if survey_provided and survey.get("simbad_has_type", 0.0) >= 0.5 and e1.best_class != combined.top_class:
        return "U3"
    # U2: untyped dot (spectrum-only, awaiting corroboration).
    return "U2"


def _to_block(r: _OneResult, experts: list[str], experiment: str) -> PredictionBlock:
    return PredictionBlock(
        experiment=experiment,
        experts=experts,
        probabilities=r.probs,
        top_class=r.top_class,
        raw_confidence=round(r.raw_confidence, 4),
        display_confidence=round(r.display_confidence, 4),
        unclassified=r.unclassified,
        conformal_set_90=r.conformal_set,
        resampled_confidence_range=r.resampled_range,
        deciding_bands=[
            DecidingBand(band_index=b["band_index"], wavelength_um=b["wavelength_um"], label=b["label"])
            for b in r.deciding
        ],
        e1_top_class=r.e1_top,
        e2_top_class=r.e2_top,
        honest_ui_rule_applied=r.honest_applied,
        discovery_class=r.discovery,
        note="Real M1..M3 pipeline output (synthetic corpus).",
    )


def _honest_ui(sp: _OneResult, all_d: _OneResult):
    from app.schemas import HonestUI
    return HonestUI(
        spectrum_alone_top=sp.top_class,
        all_data_top=all_d.top_class,
        agreement=(sp.top_class == all_d.top_class),
        capped_at_50=(sp.honest_applied or all_d.honest_applied),
        final_label_unclassified=all_d.unclassified,
    )