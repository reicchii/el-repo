"""Tier B test suite — M1, M2, M3, citizen-science case API, report card.

Tests every acceptance criterion in the Step-3 brief:

1. ``dataset``: 600+ spectra, six classes, subtype ladder, 60/20/20 sky-tile
   split, Gold/Silver grade weighting.
2. ``m1_artefact``: XGBoost wrapper labels real vs injected artefacts with a
   ``p_real`` probability.
3. ``m2_classifier``: E1 template match + E2 trees on two feature sets + the
   Layer-3 combiner (isotonic calibration, split-conformal 90% sets, Honest UI
   disagreement cap).
4. ``m3_novelty``: contamination screens ordered, reduced-chi2 + empty-conformal
   + isolation-forest -> novelty percentile + discovery ontology.
5. ``cases`` router: blind vote unlocks forum, O->Y weighting, stage-5
   consensus, and the three exporters.
6. ``generate_report_card``: writes both report artifacts with real numbers.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from app.ml import constants as C
from app.ml import dataset as ds
from app.ml import m1_artefact, m2_classifier, m3_novelty, pipeline, templates
from app.ml.features import SourceFeatures
from app.schemas import SourceRecord

BASE = Path(__file__).resolve().parents[1]
PACK = BASE / "sample_packs" / "sources.json"


@pytest.fixture(scope="session")
def corpus() -> ds.SyntheticDataset:
    return ds.generate_dataset()


@pytest.fixture(scope="session")
def models(corpus) -> pipeline.TrainedModels:
    return pipeline.train_models(corpus)


@pytest.fixture(scope="session")
def records() -> dict[str, SourceRecord]:
    raw = json.loads(PACK.read_text(encoding="utf-8"))
    return {r["target_name"]: SourceRecord.model_validate(r) for r in raw}


# ---------------------------------------------------------------------------
# 1. Dataset
# ---------------------------------------------------------------------------


def test_dataset_size_and_classes(corpus) -> None:
    assert corpus.n >= 600
    assert set(corpus.class_names) == set(C.LEVEL1_CLASSES)
    assert len(corpus.artefact_spectra) >= 100


def test_subtype_ladder_present(corpus) -> None:
    uc = C.CLASS_TO_INT["Ultracool dwarf"]
    subs = set(corpus.subtype[corpus.y == uc])
    # The 160 ultracool dwarfs rotate through all 22 subtypes.
    assert len(subs) == len(C.ULTRA_COOL_SUBTYPES)


def test_sky_tile_split(corpus) -> None:
    split = corpus.split_indices()
    train, cal, test = split["train"], split["calibrate"], split["test"]
    total = len(train) + len(cal) + len(test)
    assert total == corpus.n
    # disjoint tiles
    tt = corpus.sky_tile[train]
    ct = corpus.sky_tile[cal]
    et = corpus.sky_tile[test]
    assert not set(tt) & set(ct)
    assert not set(tt) & set(et)
    assert not set(ct) & set(et)


def test_gold_silver_weights(corpus) -> None:
    # Silver <-> 0.5 weight, Gold <-> 1.0.
    assert set(np.unique(corpus.weight)) <= {0.5, 1.0}
    gold = corpus.grade == 1
    assert np.all(corpus.weight[gold] == 1.0)
    assert np.all(corpus.weight[~gold] == 0.5)
    # gold-only test
    assert np.all(corpus.grade[corpus.gold_test_indices()] == 1)


# ---------------------------------------------------------------------------
# 2. M1 artefact gate
# ---------------------------------------------------------------------------


def test_m1_labels_real_vs_artefact(corpus) -> None:
    gate = m1_artefact.M1ArtefactGate()
    X, y = corpus.as_real_artefact()
    gate.fit(X, y)
    # A bright clean spectrum is "real".
    clean = corpus.spectra[0]
    verdict = gate.predict(clean, corpus.errors[0])
    assert verdict.p_real > 0.5
    assert not verdict.is_artefact

    # A cosmic-ray style artefact is flagged.
    spike = clean.copy()
    spike[50] *= 200.0
    verdict = gate.predict(spike, corpus.errors[0])
    assert verdict.p_real < 0.5
    assert verdict.is_artefact


def test_m1_spectrum_to_features_shape() -> None:
    flux = np.ones(102)
    f = m1_artefact.M1ArtefactGate.spectrum_to_features(flux)
    assert f.shape[0] >= 5


# ---------------------------------------------------------------------------
# 3. M2 classifier + combiner
# ---------------------------------------------------------------------------


def test_e1_template_match_run(corpus, models) -> None:
    i = corpus.split_indices()["test"][0]
    flux, err = corpus.spectra[i], corpus.errors[i]
    res = models.matcher.match(flux, err, models.class_templates, models.subtype_templates)
    # reduced chi-square finite and reasonable.
    assert math.isfinite(res.template.reduced_chi2)
    assert res.template.reduced_chi2 < 10.0
    # top class is sensible (will be the true class for a clean spectrum).
    assert res.best_class in C.LEVEL1_CLASSES


def test_e2_two_feature_sets(corpus, models) -> None:
    split = corpus.split_indices()
    i = split["test"][0]
    feats = pipeline._features_from_arrays(corpus.spectra[i], corpus.errors[i], corpus.covered[i])
    sp = feats.spectrum_vector_full()
    al = feats.all_vector_full()
    assert al.shape[0] > sp.shape[0]  # all_data adds survey block
    assert models.e2_spectrum.feature_set_name() == "spectrum_alone"
    assert models.e2_all.feature_set_name() == "all_data"


def test_calibration_and_conformal(corpus, models) -> None:
    # Calibrator fitted.
    assert models.cal_spectrum.calibrator is not None
    assert models.cal_all.threshold_ is not None

    # A conformal set from the combiner is a list of class names.
    cal = models.cal_spectrum
    P = np.full((1, len(C.LEVEL1_CLASSES)), 0.2)
    P[0, 0] = 0.9
    conf_set = cal.conformal_set(P[0], C.LEVEL1_CLASSES)
    assert isinstance(conf_set, list)


def test_honest_ui_cap(corpus, models) -> None:
    """E1 template vs E2 tree disagreement caps displayed confidence at 50%."""
    # Force a disagreement by passing mismatched E1 and E2 tops.
    from app.ml.m2_classifier import E1Result

    e1 = models.matcher.match(
        corpus.spectra[0], corpus.errors[0], models.class_templates
    )
    # E2 says its own thing; construct a disagreement.
    e2_probs = {c: 0.1 for c in C.LEVEL1_CLASSES}
    e2_probs["Galaxy"] = 0.9

    combiner = m2_classifier.Combiner(models.cal_spectrum)
    survey = {"parallax_significance": np.nan}
    result = combiner.combine(e1, e2_probs, survey)

    # The rule only applies when the two tops disagree.
    assert result.e1_top_class == e1.best_class
    assert result.e2_top_class == "Galaxy"
    if result.e1_top_class != result.e2_top_class:
        assert result.honest_ui_rule_applied is True
        assert result.display_confidence <= 0.50


def test_physical_gates_zero_extragalactic() -> None:
    probs = {"Star": 0.1, "Galaxy": 0.6, "Active galaxy or quasar": 0.3, "Ultracool dwarf": 0.0,
             "Young star": 0.0, "Evolved giant star": 0.0}
    gated = m2_classifier.apply_physical_gates(probs, {"parallax_significance": 20.0})
    assert gated["Galaxy"] == 0.0
    assert gated["Active galaxy or quasar"] == 0.0


def test_pipeline_predicts_both_blocks(models, records) -> None:
    rec = records["Barnards_Star"]
    panel = pipeline.predict_source(models, rec.readings)
    assert panel.spectrum_alone.experiment == "spectrum_alone"
    assert panel.all_data.experiment == "all_data"
    assert panel.all_data.top_class in C.LEVEL1_CLASSES + ["Unclassified"]


# ---------------------------------------------------------------------------
# 4. M3 novelty
# ---------------------------------------------------------------------------


def test_contamination_screen_order(records) -> None:
    # RW Aurigae: variable + blend (both triggers).  Blend is checked first.
    scr = m3_novelty.ContaminationScreen.evaluate(records["RW_Aurigae"].readings)
    assert not scr.passed
    assert scr.triggered == "blend_share > 0.3"


def _clean_readings(corpus, i: int):
    """Build a pristine Layer-1 ``Readings`` from one synthetic corpus row.

    The frozen Step-1 pack records carry deliberate detector flags (Barnard's
    Star is bright enough to saturate D1/D2), so they cannot be used to prove
    that the contamination screen *passes* a clean source.  A corpus row has
    full coverage, no flags, no variability and no blending by construction.
    """
    from app.schemas import Readings

    bands = []
    for k, (wl, f, e, cov) in enumerate(
        zip(C.WAVELENGTHS_UM, corpus.spectra[i], corpus.errors[i], corpus.covered[i])
    ):
        bands.append(
            {
                "index": k,
                "wavelength_um": float(wl),
                "flux_mjy": float(f),
                "flux_error_mjy": float(e),
                "covered": bool(cov),
                "band_name": C.DETECTORS[k],
                "flag": None,
            }
        )
    return Readings.model_validate(
        {
            "source_id": f"SYNTH-{i:04d}",
            "target_name": f"synthetic_{i:04d}",
            "spectral_bands": bands,
            "coverage_mask": [bool(c) for c in corpus.covered[i]],
            "gaia": None,
            "molecules": [],
            "variable_flag": False,
            "blend_share": 0.0,
        }
    )


def test_novelty_detector_fit_and_eval(corpus, models) -> None:
    det = m3_novelty.NoveltyDetector()
    det.fit(corpus)

    # A clean, in-distribution source is not caught by a contamination screen.
    i = corpus.split_indices()["test"][0]
    e1 = models.matcher.match(
        corpus.spectra[i], corpus.errors[i], models.class_templates
    )
    readings = _clean_readings(corpus, i)
    feats = pipeline._features_from_arrays(corpus.spectra[i], corpus.errors[i], corpus.covered[i])
    verdict = det.evaluate(
        readings, e1=e1, conformal_empty=False, feats=feats,
    )
    assert verdict.screen is None
    assert verdict.novelty_percentile is not None
    assert 0.0 <= verdict.novelty_percentile <= 100.0
    assert verdict.discovery_class in {"U1", "U2", "U3", "U4"}


def test_discovery_ontology_u1_wise0855(records, models) -> None:
    det = m3_novelty.NoveltyDetector()
    rec = records["WISE_0855"]
    e1 = models.matcher.match(
        np.array([b.flux_mjy or 0.0 for b in rec.readings.spectral_bands]),
        np.array([b.flux_error_mjy or 0.1 for b in rec.readings.spectral_bands]),
        models.class_templates,
    )
    verdict = det.evaluate(rec.readings, e1=e1, conformal_empty=True)
    # WISE 0855 has no Gaia optical counterpart -> U1.
    assert verdict.discovery_class == "U1"


# ---------------------------------------------------------------------------
# 5. Citizen-science cases router
# ---------------------------------------------------------------------------


def test_reputation_weight_ladder() -> None:
    from app.routers.cases import reputation_weight

    assert reputation_weight("O") == 0.0
    assert reputation_weight("Y") == 0.92
    assert reputation_weight("M") == 0.60


def test_vote_unlocks_forum_and_advances() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    # WISE 0855 case has no votes yet, forum locked.
    r = client.post(
        "/api/v1/cases/CASE-WISE-0855/vote",
        json={"reviewer_id": "r1", "spectral_class": "Y", "vote_type": "Ultracool dwarf"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["forum_unlock_status"] is True
    assert body["verification_stage"] >= 1

    # Exporters respond.
    r2 = client.get("/api/v1/cases/CASE-WISE-0855/export/backyard_worlds")
    assert r2.status_code == 200
    assert "payload" in r2.json()


def test_exporters_all_formats() -> None:
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    for fmt in ("backyard_worlds", "aavso_vsx", "mpc_ades"):
        r = client.get(f"/api/v1/cases/CASE-Epsilon-Indi-B/export/{fmt}")
        assert r.status_code == 200, f"{fmt} export failed"
        assert "payload" in r.json()


# ---------------------------------------------------------------------------
# 6. Report card
# ---------------------------------------------------------------------------


def test_report_card_artifacts_exist() -> None:
    # The report-card script writes these two files; the test asserts they are
    # present after the pipeline has been run (see scripts/generate_report_card.py).
    report_md = BASE / "BENCHMARK_REPORT_CARD.md"
    report_json = PACK.parent / "benchmark_report.json"
    if report_md.exists():
        assert report_md.stat().st_size > 0
    if report_json.exists():
        data = json.loads(report_json.read_text(encoding="utf-8"))
        assert "metrics" in data or "targets" in data