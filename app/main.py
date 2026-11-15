"""
Phantom Worlds — Tier A FastAPI application.

Serves the Layer 1 scientific readings computed *live* from the physics engines
(``app.physics.molecules`` and ``app.physics.surveys``) on top of the frozen
sample packs produced in Step 1.

Endpoints
---------
``GET  /health``
    Liveness + engine capability probe.

``GET  /api/v1/sky``
    Cone search over the 5 benchmark targets (RA, Dec, FOV in degrees) with an
    optional ``target_name`` pin.  Returns the targets whose propagated position
    falls inside the field, plus the Gaia field-star neighbours of each.

``GET  /api/v1/targets/{target_name}``
    The full payload for one benchmark target: the 102-band Layer 1 readings
    (with molecule readings re-measured by ``MoleculeEngine``), the frozen
    Layer 2/3 identity panel, cross-survey flags, and the astrometry +
    physical-gate block from ``CrossMatcher``.

``POST /api/v1/cron/ingest``
    Simulates the live SPHEREx archive update pipeline: re-runs the physics on
    every target, diffs against the frozen baseline, and reports what changed.

Design notes
------------
* Layer 1 is **recomputed**, never trusted from the pack: the pack's molecule
  block is a Step-1 snapshot, while the engine is the authoritative reader.
  This is exactly the honesty rule of section 6 — the API shows Measured data
  with its refusal reasons, never a stale number.
* Layer 2/3 predictions remain the frozen, clearly-``Estimated`` snapshot until
  the T43a–T43g ML pipeline replaces them.
* ``top_class`` (ML panel) and ``discovery_class`` (astrometry) are decoupled on
  purpose and must stay that way: WISE 0855 is honestly ``Unclassified`` by the
  spectrum-only experts while being genuinely ``U1`` (uncatalogued in Gaia
  optical) — see the Step-1 design note.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

# Windows OpenBLAS allocates too much scratch memory with many threads.
# Must be set before numpy is imported anywhere in the process.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np  # noqa: E402

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

from app.physics import closeup, molecules, surveys  # noqa: E402
from app.routers import cases as cases_router  # noqa: E402
from app.routers import community, ml_adapter  # noqa: E402
from app.schemas import MoleculeReading, Readings, SourceRecord  # noqa: E402

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parents[1]
SAMPLE_PACK_DIR = BACKEND_DIR / "sample_packs"
SOURCES_FILE = SAMPLE_PACK_DIR / "sources.json"
CASES_FILE = SAMPLE_PACK_DIR / "cases.json"
MANIFEST_FILE = SAMPLE_PACK_DIR / "manifest.json"

# Frontend SPA assets, served at / (index.html) and /pw/{*.js,*.css}.
STATIC_DIR = BACKEND_DIR / "pw"
INDEX_FILE = BACKEND_DIR / "index.html"

API_VERSION = "1.0.0"
SPHEREX_FULL_FOV_DEG = 3.5  # single SPHEREx frame is 3.5 x 11 deg; 3.5 is the tight axis

SightlineMode = Literal["brown_dwarf", "ice"]

# Billboard of the SPHEREx detectors so the API can explain coverage gaps.
DETECTOR_BANDS: dict[str, tuple[float, float]] = {
    "D1": (0.75, 1.11),
    "D2": (1.11, 1.64),
    "D3": (1.64, 2.42),
    "D4": (2.42, 3.82),
    "D5": (3.82, 4.42),
    "D6": (4.42, 5.00),
}


# ---------------------------------------------------------------------------
# Responsive models (route-level only; app/schemas.py stays frozen)
# ---------------------------------------------------------------------------


class FieldStar(BaseModel):
    """One Gaia neighbour inside the search field, for the frontend sky view."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    ra_deg: float
    dec_deg: float
    phot_g_mean_mag: Optional[float] = None
    parallax_mas: Optional[float] = None
    pmra_mas_yr: Optional[float] = None
    pmdec_mas_yr: Optional[float] = None
    separation_from_target_arcsec: Optional[float] = None
    inside_spherex_pixel: bool = Field(
        description="True when within the 6.15\" SPHEREx pixel radius of the target"
    )
    origin: Literal["Catalogue"] = "Catalogue"


class FieldContext(BaseModel):
    """Crowding context around a benchmark target."""

    model_config = ConfigDict(extra="forbid")

    field_row_count: int = Field(description="Rows in the *_gaia_dr3.csv cone-search table")
    stars_returned: int
    within_pixel_count: int
    blend_share: float
    crowding_note: str


class PhysicalGate(BaseModel):
    """Section 5E hard gates applied to the candidate type set."""

    model_config = ConfigDict(extra="forbid")

    parallax_significance: Optional[float] = None
    threshold_sigma: float = 5.0
    excluded_classes: list[str] = Field(default_factory=list)
    reason: str = ""


class AstrometryBlock(BaseModel):
    """Cross-match result, serialised for the API."""

    model_config = ConfigDict(extra="forbid")

    source_id: Optional[str] = None
    matched: bool
    separation_arcsec: Optional[float] = None
    ra_deg: Optional[float] = None
    dec_deg: Optional[float] = None
    pmra_mas_yr: Optional[float] = None
    pmdec_mas_yr: Optional[float] = None
    pm_total_mas_yr: Optional[float] = None
    parallax_mas: Optional[float] = None
    parallax_error_mas: Optional[float] = None
    parallax_significance: Optional[float] = None
    phot_g_mean_mag: Optional[float] = None
    phot_bp_mean_mag: Optional[float] = None
    phot_rp_mean_mag: Optional[float] = None
    ruwe: Optional[float] = None
    distance_pc: Optional[float] = None
    absolute_magnitude_g: Optional[float] = None
    tangential_velocity_km_s: Optional[float] = None
    reduced_proper_motion: Optional[float] = None
    blend_share: float = 0.0
    no_optical_detection: bool = Field(
        description="True when no Gaia row survives the match (WISE 0855 Y dwarf)"
    )
    origin: Literal["Catalogue"] = "Catalogue"


class MoleculeBlock(BaseModel):
    """Layer 1 molecule readings, recomputed by the engine."""

    model_config = ConfigDict(extra="forbid")

    sightline: SightlineMode
    engine: str = f"app.physics.molecules (n_resample={molecules.MoleculeEngine.__dataclass_fields__['n_resample'].default})"
    readings: list[MoleculeReading]
    refused: int
    measured: int


class SkyTargetSummary(BaseModel):
    """Compact entry for the /sky response."""

    model_config = ConfigDict(extra="forbid")

    target_name: str
    source_id: str
    ra_deg: float
    dec_deg: float
    separation_from_centre_arcsec: float
    discovery_class: str
    top_class: str
    no_optical_detection: bool
    blend_share: float
    distance_pc: Optional[float] = None
    phot_g_mean_mag: Optional[float] = None


class SkyResponse(BaseModel):
    """/api/v1/sky payload."""

    model_config = ConfigDict(extra="forbid")

    query_ra_deg: float
    query_dec_deg: float
    fov_deg: float
    epoch_mjd: float
    target_count: int
    targets: list[SkyTargetSummary]
    field_stars: list[FieldStar] = Field(
        default_factory=list, description="Gaia field stars inside the search cone"
    )
    warnings: list[str] = Field(default_factory=list)


class TargetResponse(BaseModel):
    """/api/v1/targets/{target_name} payload."""

    model_config = ConfigDict(extra="forbid")

    target_name: str
    source_id: str
    epoch_mjd: float
    readings: Readings
    molecules: MoleculeBlock
    astrometry: AstrometryBlock
    physical_gate: PhysicalGate
    field_context: FieldContext
    identity: dict[str, Any] = Field(description="Frozen Layer 2/3 identity panel")
    cross_surveys: dict[str, Any] = Field(description="Frozen cross-survey flags")
    data_quality_notes: list[str] = Field(default_factory=list)


class IngestChange(BaseModel):
    """One field that moved between the frozen pack and the live re-run."""

    model_config = ConfigDict(extra="forbid")

    target_name: str
    field: str
    frozen: Any = None
    live: Any = None
    severity: Literal["info", "warning"] = "info"


class IngestResponse(BaseModel):
    """Cron ingest report."""

    model_config = ConfigDict(extra="forbid")

    run_at: str
    epoch_mjd: float
    targets_processed: int
    new_sources: int
    changed_fields: list[IngestChange]
    packets_validated: int
    next_action: str


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_sources() -> dict[str, SourceRecord]:
    """Load and validate the frozen Step-1 pack, keyed by target name."""
    if not SOURCES_FILE.exists():
        raise RuntimeError(f"Frozen sample pack missing: {SOURCES_FILE}")
    raw = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    records = [SourceRecord.model_validate(item) for item in raw]
    return {rec.target_name: rec for rec in records}


@lru_cache(maxsize=1)
def load_cases() -> list[dict[str, Any]]:
    if not CASES_FILE.exists():
        return []
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    if not MANIFEST_FILE.exists():
        return {}
    return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Tier B ML engines (M1, M2, M3) — trained once, lazily, then cached
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def load_ml_stack() -> dict[str, Any]:
    """Train M1/M2/M3 once per process and cache the fitted stack.

    Training the synthetic corpus takes ~30 s, so it is deliberately lazy: the
    API starts instantly and only pays the cost the first time an ML endpoint is
    called.  ``lru_cache`` makes every later call free.
    """
    from app.ml import dataset as ml_dataset
    from app.ml import m1_artefact, m3_novelty, pipeline as ml_pipeline

    corpus = ml_dataset.generate_dataset()

    # M2 (E1 templates + E2 trees on both feature sets + Layer 3 combiner).
    models = ml_pipeline.train_models(corpus)

    # M1 artefact gate.
    gate = m1_artefact.M1ArtefactGate()
    X_m1, y_m1 = corpus.as_real_artefact()
    gate.fit(X_m1, y_m1)

    # M3 novelty / anomaly detector.
    detector = m3_novelty.NoveltyDetector()
    detector.fit(corpus)

    return {
        "corpus": corpus,
        "models": models,
        "gate": gate,
        "detector": detector,
    }


def real_survey_for(record: SourceRecord):
    """Map a frozen record's cross-survey flags onto the ML feature struct."""
    from app.ml.features import RealSurvey

    cs = record.cross_surveys
    return RealSurvey(
        gaia_match=cs.gaia_match,
        neowise_match=bool(cs.neowise_match),
        catwise_match=bool(cs.catwise_match),
        two_mass_match=bool(cs.two_mass_match),
        solar_system_object=cs.solar_system_object,
        simbad_type=cs.simbad_type,
        splices_class=cs.splices_class,
    )



def require_target(target_name: str) -> SourceRecord:
    sources = load_sources()
    record = sources.get(target_name)
    if record is None:
        known = ", ".join(sorted(sources))
        raise HTTPException(
            status_code=404,
            detail=f"Unknown target '{target_name}'. Benchmark targets: {known}",
        )
    return record


# ---------------------------------------------------------------------------
# Physics orchestration
# ---------------------------------------------------------------------------


def pick_sightline(record: SourceRecord) -> SightlineMode:
    """Choose the measurement convention for a target.

    Section 3 of the research doc: a *brown dwarf / cool star* index is measured
    against the 3.70–4.14 µm reference window; the *ice* convention (polynomial
    continuum + optical-depth integration) only applies to absorption occurring
    along a sightline through an ice-rich medium.  All five benchmark targets are
    objects, not background sightlines, so they all use ``brown_dwarf``.

    The ``ice`` branch is kept first-class for the upcoming background-star
    sightlines (Galactic-plane field stars) and is selectable via the
    ``?sightline=ice`` query parameter for validation runs.
    """
    return "brown_dwarf"


def measure_molecules(
    record: SourceRecord,
    sightline: SightlineMode = "brown_dwarf",
    n_resample: int = 200,
) -> MoleculeBlock:
    """Run the Layer 1 molecule engine on a source's 102-band spectrum."""
    readings = record.readings
    engine = molecules.MoleculeEngine(
        bands=readings.spectral_bands,
        variable_flag=readings.variable_flag,
        blend_share=readings.blend_share,
        sightline=sightline,
        n_resample=n_resample,
    )
    out = engine.read_all()
    measured = sum(1 for r in out if r.value is not None)
    return MoleculeBlock(
        sightline=sightline,
        readings=out,
        measured=measured,
        refused=len(out) - measured,
    )


def astrometry_for(target_name: str, epoch_mjd: float) -> tuple[surveys.CrossMatchResult, surveys.GaiaField]:
    """Cross-match a benchmark target against its Gaia field table."""
    if target_name not in surveys.TARGET_CATALOG:
        raise HTTPException(
            status_code=404,
            detail=f"No catalogue seed / Gaia field table for '{target_name}'.",
        )
    field = surveys.GaiaField.load(target_name, BACKEND_DIR)
    matcher = surveys.CrossMatcher(epoch_mjd=epoch_mjd)
    result = matcher.match(surveys.TARGET_CATALOG[target_name], field)
    return result, field


def astrometry_block(result: surveys.CrossMatchResult) -> AstrometryBlock:
    a = result.astrometry
    return AstrometryBlock(
        source_id=a.source_id,
        matched=a.matched,
        separation_arcsec=a.separation_arcsec,
        ra_deg=a.ra_deg,
        dec_deg=a.dec_deg,
        pmra_mas_yr=a.pmra_mas_yr,
        pmdec_mas_yr=a.pmdec_mas_yr,
        pm_total_mas_yr=_round(a.pm_total_mas_yr, 4),
        parallax_mas=_round(a.parallax_mas, 6),
        parallax_error_mas=a.parallax_error_mas,
        parallax_significance=_round(a.parallax_significance, 3),
        phot_g_mean_mag=_round(a.phot_g_mean_mag, 4),
        phot_bp_mean_mag=_round(a.phot_bp_mean_mag, 4),
        phot_rp_mean_mag=_round(a.phot_rp_mean_mag, 4),
        ruwe=_round(a.ruwe, 4),
        distance_pc=_round(a.distance_pc, 4),
        absolute_magnitude_g=_round(a.absolute_magnitude_g, 4),
        tangential_velocity_km_s=_round(a.tangential_velocity_km_s, 3),
        reduced_proper_motion=_round(a.reduced_proper_motion, 3),
        blend_share=round(a.blend_share, 4),
        no_optical_detection=a.no_optical_detection,
    )


def physical_gate(result: surveys.CrossMatchResult) -> PhysicalGate:
    a = result.astrometry
    sig = a.parallax_significance
    excluded = list(a.gated_out_classes)
    if excluded:
        reason = (
            f"Gaia parallax is {sig:.1f}σ (> 5σ), so the source is inside the Milky Way: "
            "extragalactic classes are hard-gated out (section 5E)."
        )
    elif a.no_optical_detection:
        reason = (
            "No Gaia optical counterpart, so no parallax gate can be applied. "
            "Core-collapse-free note: absence of a parallax does not exclude "
            "extragalactic classes — Einstein radii make a z>0.1 galaxy at PA=0 "
            "implausible [ESTIMATE], but the gate is simply not available here."
        )
    elif sig is None:
        reason = "Parallax unavailable or non-positive; extragalactic classes remain open."
    else:
        reason = f"Gaia parallax only {sig:.1f}σ; the >5σ extragalactic gate does not fire."
    return PhysicalGate(
        parallax_significance=_round(sig, 3),
        excluded_classes=excluded,
        reason=reason,
    )


def field_context(
    target_name: str,
    result: surveys.CrossMatchResult,
    field: surveys.GaiaField,
) -> FieldContext:
    """Summarise crowding around the matched target."""
    a = result.astrometry
    if not a.matched or a.ra_deg is None or a.dec_deg is None:
        return FieldContext(
            field_row_count=result.field_row_count,
            stars_returned=0,
            within_pixel_count=0,
            blend_share=0.0,
            crowding_note=(
                "No Gaia counterpart to measure crowding around. The cone-search table "
                "still holds field stars, but none belongs to this source."
            ),
        )
    return FieldContext(
        field_row_count=result.field_row_count,
        stars_returned=result.field_row_count,
        within_pixel_count=a.neighbour_count_within_pixel,
        blend_share=round(a.blend_share, 4),
        crowding_note=(
            f"{a.neighbour_count_within_pixel} Gaia neighbour(s) inside the 6.15\" "
            f"SPHEREx pixel; flux-weighted blend share {a.blend_share:.3f}."
        ),
    )


def collect_field_stars(
    field: surveys.GaiaField,
    centre_ra: float,
    centre_dec: float,
    radius_deg: float,
    target_ra: Optional[float] = None,
    target_dec: Optional[float] = None,
    limit: int = 50,
) -> list[FieldStar]:
    """Return Gaia field stars inside a cone, nearest to the target first."""
    stars: list[FieldStar] = []
    for row in field.rows:
        ra = _to_float(row.get("ra"))
        dec = _to_float(row.get("dec"))
        if ra is None or dec is None:
            continue
        sep_centre = surveys.angular_separation_arcsec(centre_ra, centre_dec, ra, dec) / 3600.0
        if sep_centre > radius_deg:
            continue
        sep_target = None
        if target_ra is not None and target_dec is not None:
            sep_target = round(surveys.angular_separation_arcsec(target_ra, target_dec, ra, dec), 3)
        stars.append(
            FieldStar(
                source_id=str(row.get("source_id", "")),
                ra_deg=ra,
                dec_deg=dec,
                phot_g_mean_mag=_to_float(row.get("phot_g_mean_mag")),
                parallax_mas=_to_float(row.get("parallax")),
                pmra_mas_yr=_to_float(row.get("pmra")),
                pmdec_mas_yr=_to_float(row.get("pmdec")),
                separation_from_target_arcsec=sep_target,
                inside_spherex_pixel=(
                    sep_target is not None and sep_target <= surveys.SPHEREX_PIXEL_RADIUS_ARCSEC
                ),
            )
        )
    stars.sort(
        key=lambda s: s.separation_from_target_arcsec
        if s.separation_from_target_arcsec is not None
        else 1e9
    )
    return stars[:limit]


def quality_notes(record: SourceRecord, block: MoleculeBlock, astro: AstrometryBlock) -> list[str]:
    """Explain, in plain words, why a reading is missing."""
    notes: list[str] = []

    uncovered = [b.band_name for b in record.readings.spectral_bands if not b.covered]
    uncovered_unique = sorted(set(uncovered))
    if uncovered_unique:
        notes.append(
            f"Coverage mask: {len(uncovered)}/102 bands not covered "
            f"(detectors {', '.join(uncovered_unique)})."
        )

    if astro.no_optical_detection:
        notes.append(
            "No Gaia optical counterpart: the object is invisible in the optical bands "
            "and is detected only in the infrared (D5–D6)."
        )
    if record.readings.variable_flag:
        notes.append("Flagged variable between visits: amplitude-dependent readings are refused.")
    if record.readings.blend_share > 0.3:
        notes.append(
            f"Blend share {record.readings.blend_share:.2f} exceeds the 0.30 threshold: "
            "photometry cannot be split reliably between components."
        )
    for reading in block.readings:
        if reading.refusal_reason:
            notes.append(f"{reading.molecule}: {reading.refusal_reason}")
    return notes


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _round(value: Optional[float], ndigits: int) -> Optional[float]:
    return None if value is None else round(value, ndigits)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Phantom Worlds API — Tier A + Tier B",
    description=(
        "Layer 1 scientific readings (102-band SPHEREx spectrophotometry, molecule "
        "indices, Gaia astrometry and physical gates) plus the Tier B ML identity "
        "panel and the Pillar 3/4 citizen-science case API.  Every number carries an "
        "origin label; refused readings state their reason."
    ),
    version=API_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # hackathon build; pin to the frontend origin before release
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_store_for_app_shell(request, call_next):
    """Never let a browser reuse an old copy of the app shell or its scripts.

    A stale cached ``core.js`` is what makes a fixed build keep showing the old
    behaviour, so the shell and its assets are always revalidated. Data endpoints
    keep their own caching rules.
    """
    response = await call_next(request)
    path = request.url.path
    if path in ("/", "/index.html") or path.startswith("/pw/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Register the Pillar 3/4 citizen-science router (votes + dossier exports).
app.include_router(cases_router.router)

# Community finds store (SPA: share, comments, up/down votes, Lab review).
app.include_router(community.router)

# ML adapter ("ML Nyusul" ready): GET /api/ml/predict/{field}/{src_id}.
app.include_router(ml_adapter.router)

# SPA static assets. /pw mirrors <link href="pw/app.css"> and <script src="pw/core.js">.
if STATIC_DIR.is_dir():
    app.mount("/pw", StaticFiles(directory=str(STATIC_DIR)), name="pw")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the vanilla-JS single page app at the root."""
    if INDEX_FILE.exists():
        return FileResponse(INDEX_FILE)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["ops"])
def health() -> dict[str, Any]:
    """Liveness probe plus a capability check on both API tiers.

    ``tier_a`` covers the Layer 1 physics engines; ``tier_b`` reports the M1/M2/M3
    ML engines.  The ML stack is trained lazily, so ``tier_b.trained`` is False
    until the first ML request (or a warm-up) has run — the process is healthy in
    either state.
    """
    sources = load_sources()
    ml_ready = load_ml_stack.cache_info().currsize > 0

    tier_b: dict[str, Any] = {
        "trained": ml_ready,
        "warm_up_endpoint": "/api/v1/predict/{target_name}",
        "engines": {
            "M1": {
                "name": "artefact gate",
                "model": "xgboost.XGBClassifier",
                "outputs": "p_real (rejects cosmic rays, ghost pixels, D5/D6 glow)",
            },
            "M2": {
                "name": "two-level type classifier + combiner",
                "experts": {
                    "E1": "template matcher (numpy, analytic scale, reduced chi2)",
                    "E2": "XGBClassifier on spectrum_alone and all_data",
                },
                "layer3": "OOF LogisticRegression stack + isotonic calibration + split conformal 90%",
                "honest_ui": "E1/E2 disagreement caps confidence at 50%; <50% or empty set = Unclassified",
            },
            "M3": {
                "name": "novelty & anomaly detector",
                "screens": ["blend_share > 0.3", "visit-to-visit variability", "overflow/ghost flags"],
                "signals": ["reduced chi2 > 3", "empty conformal set", "IsolationForest"],
                "ontology": ["U1", "U2", "U3", "U4"],
            },
        },
    }
    if ml_ready:
        stack = load_ml_stack()
        tier_b["metrics"] = {
            k: (round(v, 6) if isinstance(v, float) else v)
            for k, v in stack["models"].metrics.items()
        }
        tier_b["corpus_size"] = stack["corpus"].n

    return {
        "status": "ok",
        "api_version": API_VERSION,
        "targets_loaded": len(sources),
        "targets": sorted(sources),
        "tier_a": {
            "path": "app/physics",
            "engines": {
                "molecules": "app.physics.molecules.MoleculeEngine",
                "surveys": "app.physics.surveys.CrossMatcher",
                "monte_carlo_resamples": molecules.MoleculeEngine.__dataclass_fields__["n_resample"].default,
            },
            "epochs": {
                "gaia_dr3_mjd": surveys.GAIA_DR3_REF_EPOCH_MJD,
                "j2000_mjd": surveys.J2000_EPOCH_MJD,
                "spherex_nominal_mjd": surveys.SPHEREX_NOMINAL_EPOCH_MJD,
            },
        },
        "tier_b": tier_b,
        # Kept for backwards compatibility with the Step-2 health contract.
        "engines": {
            "molecules": "app.physics.molecules.MoleculeEngine",
            "surveys": "app.physics.surveys.CrossMatcher",
            "monte_carlo_resamples": molecules.MoleculeEngine.__dataclass_fields__["n_resample"].default,
        },
        "generated_at": _now_iso(),
    }


@app.get("/api/v1/sky", response_model=SkyResponse, tags=["layer1"])
def sky(
    ra: Annotated[float, Query(ge=0.0, le=360.0, description="Field centre RA, degrees (J2000/J2016 mixed)")],
    dec: Annotated[float, Query(ge=-90.0, le=90.0, description="Field centre Dec, degrees")],
    fov: Annotated[float, Query(gt=0.0, le=30.0, description="Search radius, degrees")] = SPHEREX_FULL_FOV_DEG,
    target_name: Annotated[Optional[str], Query(description="Pin one benchmark target")] = None,
    epoch_mjd: Annotated[float, Query(description="Epoch to propagate positions to")] = surveys.SPHEREX_NOMINAL_EPOCH_MJD,
    include_field_stars: Annotated[bool, Query(description="Append Gaia field stars inside the cone")] = True,
) -> SkyResponse:
    """Cone search over the benchmark targets (and their Gaia field stars).

    Positions come from the cross-matcher, propagated to ``epoch_mjd``, so high
    proper-motion targets (Barnard's Star moves ~166″/decade) land where they
    actually are at the SPHEREx epoch rather than at their catalogue position.
    """
    sources = load_sources()
    warnings: list[str] = []

    if target_name is not None and target_name not in sources:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown target '{target_name}'. Benchmark targets: {', '.join(sorted(sources))}",
        )

    candidates = [target_name] if target_name else sorted(sources)
    targets: list[SkyTargetSummary] = []
    field_stars: list[FieldStar] = []

    for name in candidates:
        record = sources[name]
        result, field = astrometry_for(name, epoch_mjd)
        a = result.astrometry

        if a.matched and a.ra_deg is not None and a.dec_deg is not None:
            pos_ra, pos_dec = a.ra_deg, a.dec_deg
        else:
            seed = surveys.TARGET_CATALOG[name]
            pos_ra, pos_dec = surveys.propagate(
                seed.ra_j2000_deg,
                seed.dec_j2000_deg,
                seed.pmra_mas_yr or 0.0,
                seed.pmdec_mas_yr or 0.0,
                surveys.J2000_EPOCH_MJD,
                epoch_mjd,
            )

        sep_centre_arcsec = surveys.angular_separation_arcsec(ra, dec, pos_ra, pos_dec)
        if sep_centre_arcsec > fov * 3600.0:
            continue

        targets.append(
            SkyTargetSummary(
                target_name=name,
                source_id=record.source_id,
                ra_deg=round(pos_ra, 6),
                dec_deg=round(pos_dec, 6),
                separation_from_centre_arcsec=round(sep_centre_arcsec, 2),
                discovery_class=record.identity.all_data.discovery_class,
                top_class=record.identity.all_data.top_class,
                no_optical_detection=a.no_optical_detection,
                blend_share=round(record.readings.blend_share, 4),
                distance_pc=_round(a.distance_pc, 3),
                phot_g_mean_mag=_round(a.phot_g_mean_mag, 3),
            )
        )

        if a.no_optical_detection:
            warnings.append(
                f"{name}: no Gaia optical counterpart — position taken from the IR "
                "moving-source catalogue seed, not from a matched star."
            )

        if include_field_stars and len(candidates) == 1:
            field_stars = collect_field_stars(
                field,
                centre_ra=ra,
                centre_dec=dec,
                radius_deg=fov,
                target_ra=a.ra_deg if a.matched else pos_ra,
                target_dec=a.dec_deg if a.matched else pos_dec,
            )

    targets.sort(key=lambda t: t.separation_from_centre_arcsec)
    if not targets:
        warnings.append(
            f"No benchmark target within {fov}° of RA={ra} Dec={dec}. "
            f"The pack covers: {', '.join(sorted(sources))}."
        )

    return SkyResponse(
        query_ra_deg=ra,
        query_dec_deg=dec,
        fov_deg=fov,
        epoch_mjd=epoch_mjd,
        target_count=len(targets),
        targets=targets,
        field_stars=field_stars,
        warnings=warnings,
    )


@app.get("/api/v1/targets/{target_name}", response_model=TargetResponse, tags=["layer1"])
def get_target(
    target_name: str,
    epoch_mjd: Annotated[float, Query(description="Epoch for the cross-match")] = surveys.SPHEREX_NOMINAL_EPOCH_MJD,
    sightline: Annotated[Optional[SightlineMode], Query(description="Override the measurement convention")] = None,
) -> TargetResponse:
    """Full Layer 1 payload for one benchmark target.

    The molecule block is **recomputed** by ``MoleculeEngine`` (Monte Carlo,
    200 resamples). Layer 2/3 predictions are served from the frozen Step-1 pack
    and stay labelled ``Estimated``.
    """
    record = require_target(target_name)

    mode = sightline or pick_sightline(record)
    block = measure_molecules(record, sightline=mode)

    result, field = astrometry_for(target_name, epoch_mjd)
    astro = astrometry_block(result)

    readings = record.readings.model_copy(
        update={
            "molecules": block.readings,
            # Never show an unmeasured blend share: the engine recomputes it.
            "blend_share": max(record.readings.blend_share, astro.blend_share),
        }
    )

    return TargetResponse(
        target_name=record.target_name,
        source_id=record.source_id,
        epoch_mjd=epoch_mjd,
        readings=readings,
        molecules=block,
        astrometry=astro,
        physical_gate=physical_gate(result),
        field_context=field_context(target_name, result, field),
        identity=record.identity.model_dump(mode="json"),
        cross_surveys=record.cross_surveys.model_dump(mode="json"),
        data_quality_notes=quality_notes(record, block, astro),
    )


@app.get("/api/v1/predict/{target_name}", tags=["ml"])
def predict_target(
    target_name: str,
    resample_times: Annotated[
        int, Query(ge=0, le=500, description="Spectrum resamples within flux errors (0 disables)")
    ] = 100,
    epoch_mjd: Annotated[float, Query(description="Epoch for the astrometry fed to E4-E7")] = surveys.SPHEREX_NOMINAL_EPOCH_MJD,
) -> dict[str, Any]:
    """Run the full M1 -> M2 -> M3 pipeline live for one benchmark target.

    Unlike ``/api/v1/targets/{name}`` (which serves the frozen Step-1 identity
    panel), this endpoint re-executes everything from the 102-band spectrum and
    the real cross-survey flags on each call.  It exists so the frontend can
    trigger the ML panel on demand rather than only reading the sample pack.

    Latest SPHEREx astrometry is used wherever available: the ``blend_share``
    is refreshed from the cone-search cross-matcher before M1 runs, so the M3
    contamination screens see current values rather than the frozen ones.
    """
    record = require_target(target_name)
    stack = load_ml_stack()
    models = stack["models"]

    from app.ml import pipeline as ml_pipeline
    from app.ml.features import SourceFeatures

    # Refresh blend share from the live field-star crowding (Section 5E).
    try:
        live_blend = astrometry_block(astrometry_for(target_name, epoch_mjd)[0]).blend_share
    except Exception:
        live_blend = record.readings.blend_share

    readings = record.readings.model_copy(
        update={"blend_share": max(record.readings.blend_share, live_blend)}
    )
    survey = real_survey_for(record)

    # -- M1: artefact gate ---------------------------------------------------
    flux = np.array(
        [b.flux_mjy if (b.covered and b.flux_mjy is not None) else 0.0
         for b in readings.spectral_bands],
        dtype=float,
    )
    err = np.array(
        [b.flux_error_mjy if b.flux_error_mjy is not None else 1e-6
         for b in readings.spectral_bands],
        dtype=float,
    )
    verdict = stack["gate"].predict(flux, err)

    # -- M2: two-level classifier + combiner ---------------------------------
    panel = ml_pipeline.predict_source(models, readings, survey=survey, resample_times=resample_times)

    # -- M3: novelty + discovery ontology ------------------------------------
    feats = SourceFeatures.from_readings(readings, survey)
    e1 = models.matcher.match(feats.spectrum, feats.errors, models.class_templates)
    nov = stack["detector"].evaluate(
        readings,
        e1=e1,
        conformal_empty=not panel.all_data.conformal_set_90,
        feats=feats,
        survey=feats.survey,
    )

    return {
        "target_name": record.target_name,
        "source_id": record.source_id,
        "epoch_mjd": epoch_mjd,
        "computed_live": True,
        "m1_artefact_gate": {
            "p_real": round(float(verdict.p_real), 6),
            "is_artefact": bool(verdict.is_artefact),
            "artefact_kind": verdict.artefact_kind,
            "reason": verdict.reason,
        },
        "m2_identity": json.loads(panel.model_dump_json()),
        "m3_novelty": {
            "novelty_percentile": round(float(nov.novelty_percentile), 2),
            "is_novel": bool(nov.is_novel),
            "discovery_class": nov.discovery_class,
            "reasons": nov.reasons,
            "screen": nov.screen,
            "reduced_chi2": (None if nov.reduced_chi2 is None else round(float(nov.reduced_chi2), 4)),
        },
        "provenance": {
            "spectrum": "Measured (frozen SPHEREx-like 102-band benchmark spectrum)",
            "astrometry": "Catalogue (Gaia DR3 / WISE cone-search cross-match)",
            "ml_output": "Estimated (live M1-M3 inference; not a confirmed type)",
        },
        "generated_at": _now_iso(),
    }


@app.post("/api/v1/cron/ingest", response_model=IngestResponse, tags=["ops"])
def cron_ingest(
    epoch_mjd: Annotated[float, Query(description="Epoch for the re-run")] = surveys.SPHEREX_NOMINAL_EPOCH_MJD,
    resamples: Annotated[int, Query(ge=50, le=1000, description="Monte Carlo resamples")] = 200,
) -> IngestResponse:
    """Re-run the physics on every target and diff against the frozen pack.

    This is the hook the live SPHEREx archive poller will call (queue worker or
    cron).  Each invocation is idempotent: it never mutates the frozen pack, it
    only reports what a real ingest would change.
    """
    sources = load_sources()
    changes: list[IngestChange] = []
    new_sources = 0
    packets_validated = 0

    for name, record in sorted(sources.items()):
        block = measure_molecules(record, sightline=pick_sightline(record), n_resample=resamples)
        frozen = {m.molecule: m for m in record.readings.molecules}

        for reading in block.readings:
            before = frozen.get(reading.molecule)
            if before is None:
                new_sources += 1
                continue
            if before.refusal_reason != reading.refusal_reason:
                changes.append(
                    IngestChange(
                        target_name=name,
                        field=f"molecules.{reading.molecule}.refusal_reason",
                        frozen=before.refusal_reason,
                        live=reading.refusal_reason,
                        severity="warning",
                    )
                )
            if (
                before.value is not None
                and reading.value is not None
                and abs(before.value - reading.value) > 0.05
            ):
                changes.append(
                    IngestChange(
                        target_name=name,
                        field=f"molecules.{reading.molecule}.value",
                        frozen=before.value,
                        live=reading.value,
                    )
                )

        result, _ = astrometry_for(name, epoch_mjd)
        a = result.astrometry
        if record.readings.blend_share != round(a.blend_share, 4) and a.matched:
            changes.append(
                IngestChange(
                    target_name=name,
                    field="readings.blend_share",
                    frozen=record.readings.blend_share,
                    live=round(a.blend_share, 4),
                )
            )
        if a.matched and a.parallax_mas is not None:
            frozen_plx = record.readings.gaia.parallax_mas if record.readings.gaia else None
            if frozen_plx is not None and abs(frozen_plx - a.parallax_mas) > 0.001:
                changes.append(
                    IngestChange(
                        target_name=name,
                        field="readings.gaia.parallax_mas",
                        frozen=round(frozen_plx, 6),
                        live=round(a.parallax_mas, 6),
                        severity="warning",
                    )
                )

    for case in load_cases():
        if case.get("export_packets"):
            packets_validated += 1

    return IngestResponse(
        run_at=_now_iso(),
        epoch_mjd=epoch_mjd,
        targets_processed=len(sources),
        new_sources=new_sources,
        changed_fields=changes,
        packets_validated=packets_validated,
        next_action=(
            "No drift: frozen pack matches the live engines."
            if not changes
            else f"{len(changes)} field(s) drift from the frozen pack — review before publishing."
        ),
    )


@app.get("/api/v1/cases", tags=["citizen-science"])
def list_cases() -> list[dict[str, Any]]:
    """Frozen Pillar 3/4 case records (verification stage, vote tally, exports)."""
    return load_cases()


# ---------------------------------------------------------------------------
# Close-up rendering for Sky Explorer (Source and Pixel zoom levels)
# ---------------------------------------------------------------------------


@app.get("/api/v1/cutout/{field}/{src_id}", tags=["layer1"])
def cutout(
    field: str,
    src_id: str,
    zoom: Annotated[
        str,
        Query(
            description=(
                "Zoom level from the interface: sky, field, source or pixel. "
                "Source and pixel return the 4x oversampled close-up."
            )
        ),
    ] = "field",
    os_factor: Annotated[
        int,
        Query(alias="os", ge=1, le=8, description="Oversampling factor. 1 returns the raw binned frame."),
    ] = 0,
    size: Annotated[int, Query(ge=8, le=128, description="Cutout width in native 6.15\" pixels.")] = 24,
) -> dict[str, Any]:
    """Return one field source at the requested zoom level.

    Section 10.3: the ``Source`` level shows *"4x upsampled stacks"*; the ``Pixel``
    level shows *"the 6.15\" pixel grid with values on hover"*.  Section 10.1.7
    requires honest images, so the response always names which of the two renderings
    it is and what its numbers are worth:

    * ``mode: raw``      — the binned frame. ``origin: Measured``.
    * ``mode: enhanced`` — 4x oversampled. ``origin: Estimated``.

    A field or source the pack does not hold is a 404 with the empty-state sentence
    from section 5.6, not an empty grid.
    """
    zoom_key = (zoom or "field").strip().lower()
    if zoom_key not in ("sky", "field", "source", "pixel"):
        raise HTTPException(
            status_code=422,
            detail="zoom must be one of sky, field, source or pixel. Open a field and try again.",
        )

    mode = closeup.mode_for_zoom(zoom_key)
    if os_factor:
        # The caller may pin the factor: 1 is the raw frame, anything else is the
        # oversampled rendering, and the label follows so the readout never lies.
        mode = closeup.MODES["raw"] if os_factor == 1 else {
            **closeup.MODES["enhanced"],
            "oversample": os_factor,
            "pixel_arcsec": round(closeup.PIXEL_ARCSEC / os_factor, 4),
            "label": f"{os_factor}x oversampled PSF model (Estimated)",
        }

    pack = _pack_for_field(field)
    if pack is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"SPHEREx has no prepared frames of the {field} field yet. "
                "Open one of the ready-made test fields."
            ),
        )

    source = next((s for s in pack["sources"] if s.get("id") == src_id), None)
    if source is None:
        raise HTTPException(
            status_code=404,
            detail=f"{src_id} is not in the {field} field. Pick a source on the image.",
        )

    detector = str(source.get("detector") or "D6")
    visit = int(source.get("visit") or 1)
    try:
        rendered = closeup.render_closeup(
            field=pack,
            source=source,
            detector=detector,
            visit=visit,
            mode=mode,
            size=size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{exc}. Lower the cutout size and retry.") from exc

    return {
        "field": field,
        "source_id": src_id,
        "zoom": zoom_key,
        "ra_deg": pack.get("ra"),
        "dec_deg": pack.get("dec"),
        "data_as_of": pack.get("data_as_of"),
        "pipeline_version": pack.get("pipeline_version"),
        **rendered,
    }


def _pack_for_field(field: str) -> Optional[dict[str, Any]]:
    """Build the render table for a field from the frozen pack.

    The pack holds the five benchmark targets.  Each becomes a one-source field so
    the same renderer serves them and any later real pack without changing shape.
    The source is listed under both its archive source id and its target name, so a
    caller may address it either way.
    """
    sources = load_sources()
    record = sources.get(MAPPED_TARGETS.get(field, field))
    if record is None:
        return None
    bands = [b.model_dump() for b in record.readings.spectral_bands]
    entry = {
        "x": 0.0,
        "y": 0.0,
        "flux": None,
        "spectral_bands": bands,
        "sn": None,
        "detector": "D6",
        "visit": 1,
    }
    ids = {record.target_name, record.source_id or record.target_name, MAPPED_SOURCE_ID.get(field, "")}
    return {
        "id": field,
        "ra": None,
        "dec": None,
        "data_as_of": (load_manifest() or {}).get("generated_at"),
        "pipeline_version": API_VERSION,
        "sources": [{"id": sid, **entry} for sid in sorted(i for i in ids if i)],
    }


#: Field identifiers the interface uses, mapped to the benchmark target names.
MAPPED_TARGETS: dict[str, str] = {
    "wise0855": "WISE_0855",
    "barnard": "Barnards_Star",
    "epsindi": "Epsilon_Indi_B",
    "rwaur": "RW_Aurigae",
    "rdra": "R_Draconis",
}

#: The source id the interface puts in the URL for each field.
MAPPED_SOURCE_ID: dict[str, str] = {
    "wise0855": "W0855",
    "barnard": "BARN",
    "epsindi": "EPSB",
    "rwaur": "RWAUR",
    "rdra": "RDRA",
}



@app.get("/api/v1/manifest", tags=["ops"])
def get_manifest() -> dict[str, Any]:
    """Frozen bundle metadata, so clients can discover and validate the pack."""
    manifest = load_manifest()
    if not manifest:
        raise HTTPException(status_code=503, detail="manifest.json has not been generated yet.")
    return manifest
