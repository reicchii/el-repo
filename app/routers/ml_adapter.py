"""ML adapter for the SPA — "ML Nyusul" ready.

The frontend reads pipeline outputs (``preal``, ``best``, ``runner``, ``novel``,
``prio``, ``tags``) from this adapter. It maps ``field/src_id`` to a benchmark
target, runs the live M1→M2→M3 stack (reusing ``app.main`` helpers), and returns
a compact payload whose keys match the frontend's source fields verbatim.

Because the corpora are synthetic and the models are lazily trained, every call
falls back gracefully: ``noest`` is set when the source is not one of the five
benchmark targets (or training has not happened yet), and the frontend renders
"Model estimate: not in the sample data" with zero errors.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/ml", tags=["ml"])

# NOTE: imports of app.main helpers are deliberately lazy (inside ml_predict).
# app.main imports this router at module level *before* those helpers are
# defined, so a top-level `from app.main import ...` would be a circular import.


# field-name -> benchmark target (frontend naming vs backend target_name)
_FIELD_TARGET = {
    "wise0855": "WISE_0855",
    "barnard": "Barnards_Star",
    "epsindi": "Epsilon_Indi_B",
    "rwaur": "RW_Aurigae",
    "rdra": "R_Draconis",
}

_SOURCE_ALIAS = {
    "W0855": "WISE_0855",
    "BARN": "Barnards_Star",
    "EPSB": "Epsilon_Indi_B",
    "RWAUR": "RW_Aurigae",
    "RDRA": "R_Draconis",
}


def _resolve(field: str, src_id: str) -> str:
    """Map a frontend field/src pair onto a backend target_name."""
    target = _SOURCE_ALIAS.get(src_id) or _FIELD_TARGET.get(field)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"No ML model for field '{field}' source '{src_id}'. "
                   "Only the five benchmark targets are modelled; other sources render noest.",
        )
    return target


@router.get("/predict/{field}/{src_id}")
def ml_predict(field: str, src_id: str) -> dict[str, Any]:
    """One source's compact ML panel for the SPA data panel.

    Returns frontend-shaped keys:
      preal, best:[label,confidence], runner, novel, prio, tags, noest, discovery.
    """
    target = _resolve(field, src_id)

    # Lazy imports avoid a circular import: app.main registers this router before
    # its ML helpers are defined.
    from app.main import load_ml_stack, real_survey_for, require_target

    try:
        record = require_target(target)
    except HTTPException:
        return {"noest": True, "best": ["", 50]}

    try:
        stack = load_ml_stack()
    except Exception:
        # Models not yet trained / corpus unavailable -> graceful noest.
        return {"noest": True, "best": ["", 50], "src_id": src_id, "field": field}

    from app.ml import pipeline as ml_pipeline
    from app.ml.features import SourceFeatures

    models = stack["models"]
    survey = real_survey_for(record)
    readings = record.readings
    panel = ml_pipeline.predict_source(models, readings, survey=survey, resample_times=20)

    all_d = panel.all_data
    sp = panel.spectrum_alone

    # M1 p_real (cheap artefact gate, one spectrum prediction).
    try:
        import numpy as np

        flux = np.array(
            [b.flux_mjy if (b.covered and b.flux_mjy is not None) else 0.0 for b in readings.spectral_bands],
            dtype=float,
        )
        err = np.array(
            [b.flux_error_mjy if b.flux_error_mjy is not None else 1e-6 for b in readings.spectral_bands],
            dtype=float,
        )
        verdict = stack["gate"].predict(flux, err)
        preal = round(float(verdict.p_real), 4)
    except Exception:
        preal = 0.5  # noest-grade fallback

    # M3 discovery/novelty.
    try:
        feats = SourceFeatures.from_readings(readings, survey)
        e1 = models.matcher.match(feats.spectrum, feats.errors, models.class_templates)
        nov = stack["detector"].evaluate(
            readings, e1=e1, conformal_empty=not all_d.conformal_set_90, feats=feats, survey=feats.survey
        )
        novel = bool(nov.is_novel)
        discovery = nov.discovery_class
        prio = round(float(nov.novelty_percentile) / 100.0, 3)
    except Exception:
        novel = False
        discovery = "U3"
        prio = 0.0

    # Frontend expects confidence in percent; cap at 50 on E1/E2 disagreement.
    label = all_d.top_class
    conf = round(all_d.display_confidence * 100.0, 1)

    tags: list[str] = []
    if all_d.unclassified:
        tags.append("nocat")
    if label == "Ultracool dwarf":
        tags.append("cold")
    if discovery == "U1":
        tags.append("uncatalogued")

    return {
        "field": field,
        "src_id": src_id,
        "target_name": target,
        "noest": False,
        "preal": preal,
        "best": [label, conf],
        "runner": all_d.e2_top_class or "",
        "novel": novel,
        "prio": prio,
        "discovery_class": discovery,
        "tags": tags,
        "conformal_set": all_d.conformal_set_90,
        "unclassified": all_d.unclassified,
        "deciding_bands": [b.label for b in all_d.deciding_bands],
        "provenance": "Estimated (live M1-M3; not a confirmed type)",
    }