"""
Tier A test suite — Layer 1 molecule engine, Gaia cross-matcher, and API shell.

The four acceptance assertions map 1:1 to the Step-2 brief:

    (a) Epsilon Indi B       -> significant CH4 methane dip (>= 5 sigma)
    (b) Barnard's Star       -> no methane dip, parallax ~546.9 mas
    (c) RW Aurigae           -> variability / blend refusal rule
    (d) WISE 0855            -> no optical counterpart + D1-D4 coverage refusal

Plus a small set of scaffold checks (imports, /health, a 404, and the CORS +
schema round-trip) that prove the FastAPI application boots and serves the
frozen pack.

Design invariants under test (from the Step-1 freeze):
* ``readings.molecules`` in the sample pack is a *snapshot*; the authoritative
  reader is ``MoleculeEngine``.  Tests therefore call the engine directly for
  physics assertions and exercise the API only for wiring/transport.
* Layer 2/3 predictions stay ``Estimated``; only Layer 1 is ``Measured`` here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import main
from app.physics import molecules, surveys
from app.schemas import MoleculeReading, SourceRecord

BACKEND_DIR = Path(__file__).resolve().parents[1]
SAMPLE_PACK = BACKEND_DIR / "sample_packs" / "sources.json"

# All five benchmark targets required by the brief.
REQUIRED_TARGETS = ["Barnards_Star", "Epsilon_Indi_B", "R_Draconis", "RW_Aurigae", "WISE_0855"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def sources() -> dict[str, SourceRecord]:
    """Validated Step-1 pack, keyed by target name."""
    assert SAMPLE_PACK.exists(), f"frozen pack missing: {SAMPLE_PACK}"
    import json

    records = [SourceRecord.model_validate(item) for item in json.loads(SAMPLE_PACK.read_text(encoding="utf-8"))]
    return {rec.target_name: rec for rec in records}


@pytest.fixture(scope="session")
def readings(sources):
    """Map of target_name -> readings from the molecule engine (200 resamples)."""

    def build(record: SourceRecord) -> dict[str, MoleculeReading]:
        engine = molecules.MoleculeEngine(
            bands=record.readings.spectral_bands,
            variable_flag=record.readings.variable_flag,
            blend_share=record.readings.blend_share,
            sightline="brown_dwarf",
            n_resample=200,
        )
        return {r.molecule: r for r in engine.read_all()}

    return {name: build(record) for name, record in sources.items()}


@pytest.fixture(scope="session")
def astrometry(sources):
    """Map of target_name -> cross-match result."""
    results = {}
    for name in REQUIRED_TARGETS:
        field = surveys.GaiaField.load(name, BACKEND_DIR)
        matcher = surveys.CrossMatcher(epoch_mjd=surveys.SPHEREX_NOMINAL_EPOCH_MJD)
        results[name] = matcher.match(surveys.TARGET_CATALOG[name], field)
    return results


# ---------------------------------------------------------------------------
# Scaffold: the application boots and routes work
# ---------------------------------------------------------------------------


def test_app_imports_and_root_documentation() -> None:
    assert main.app is not None
    assert "Phantom Worlds API" in main.app.title
    # CORS middleware must be present (frontend team dependency).
    # Starlette wraps registered middleware in ``Middleware(cls, **kwargs)``.
    assert any(getattr(mw, "cls", None).__name__ == "CORSMiddleware" for mw in main.app.user_middleware)


def test_frozen_pack_roundtrips_through_pydantic(sources) -> None:
    """Step-1 freeze: every target validates against app/schemas.py."""
    assert set(sources) == set(REQUIRED_TARGETS)
    for rec in sources.values():
        assert len(rec.readings.spectral_bands) == 102
        assert len(rec.readings.coverage_mask) == 102


def test_health_endpoint() -> None:
    payload = main.health()
    assert payload["status"] == "ok"
    assert payload["targets_loaded"] == 5
    assert set(payload["targets"]) == set(REQUIRED_TARGETS)


def test_target_404_for_unknown_name() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        assert main.require_target("Not_A_Target")
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Acceptance (a): Epsilon Indi B methane dip, >= 5 sigma
# ---------------------------------------------------------------------------


def test_epsilon_indi_b_shows_significant_ch4(readings) -> None:
    ch4 = readings["Epsilon_Indi_B"]["CH4"]

    # The methane feature must be *measured* (no refusal)...
    assert ch4.value is not None, f"CH4 reading was refused: {ch4.refusal_reason}"
    assert ch4.origin == "Measured"
    assert ch4.sigma is not None

    # ...and it must be a positive dip (absorption) at >= 5 sigma.
    # The engine produces ~+0.60 mag at ~18.8 sigma; assert the physical gate,
    # not the exact seed-dependent number.
    assert ch4.value > 0, "expected a positive CH4 absorption index for Eps Ind B"
    assert ch4.sigma >= 5.0, f"CH4 significance {ch4.sigma} is below the 5-sigma gate"

    # MC error range must be sane (16th percentile below median, 84th above).
    lo, hi = ch4.error_16_84
    assert lo <= ch4.value <= hi
    assert lo < hi


# ---------------------------------------------------------------------------
# Acceptance (b): Barnard's Star — no methane dip + 546.9 mas parallax
# ---------------------------------------------------------------------------


def test_barnards_star_has_no_significant_ch4(readings) -> None:
    ch4 = readings["Barnards_Star"]["CH4"]
    assert ch4.value is not None, f"CH4 was refused unexpectedly: {ch4.refusal_reason}"

    # The rotationally-hot M4 dwarf shows no methane absorption: the index is
    # *negative* (flux at 3.3 um sits ABOVE the cooler reference window), the
    # opposite of the deep positive dip seen in Epsilon Indi B.  A negative
    # sigma simply means the significance points *away* from a methane dip.
    assert ch4.value < 0, f"Barnard's Star CH4 index {ch4.value} is not dip-free"
    assert ch4.sigma < 0, f"Barnard's Star CH4 at {ch4.sigma} sigma points toward a dip"


def test_barnards_star_matches_546_9_mas_parallax_row(astrometry) -> None:
    a = astrometry["Barnards_Star"].astrometry

    # The cross-matcher must find the field row (never a blind row[0]).
    assert a.matched is True
    assert a.source_id == "4472832130942575872"

    # Literature / Step-1 parallax is 546.976 mas; the brief's "546.9 mas" is
    # that value expressed to one decimal place.
    assert a.parallax_mas is not None
    assert a.parallax_mas == pytest.approx(546.975939730948, rel=1e-4)
    assert a.parallax_mas == pytest.approx(546.9, abs=0.1)

    # Derived distance sanity: Barnard's Star is ~1.83 pc.
    assert a.distance_pc == pytest.approx(1.828, rel=1e-2)


# ---------------------------------------------------------------------------
# Acceptance (c): RW Aurigae triggers refusal rules
# ---------------------------------------------------------------------------


def test_rw_aurigae_refuses_molecule_readings(readings, astrometry) -> None:
    a = astrometry["RW_Aurigae"].astrometry

    # The *blend* trigger is real, not faked: a neighbour sits well inside the
    # 6.15" SPHEREx pixel with a flux-weighted share above the 0.3 threshold.
    assert a.neighbour_count_within_pixel >= 1
    assert a.blend_share > 0.3

    # The *variability* trigger is also real.
    assert readings["RW_Aurigae"]["CH4"].refusal_reason is not None
    assert readings["RW_Aurigae"]["CH4"].refusal_reason == "Not measured: the source varies between visits"

    # Every molecule is refused with a non-empty, explicit reason.
    for mreading in readings["RW_Aurigae"].values():
        assert mreading.value is None
        assert mreading.refusal_reason, "a refused reading must carry its reason"


# ---------------------------------------------------------------------------
# Acceptance (d): WISE 0855 — no optical counterpart + D1-D4 coverage refusal
# ---------------------------------------------------------------------------


def test_wise_0855_no_optical_detection(astrometry) -> None:
    a = astrometry["WISE_0855"].astrometry
    assert a.no_optical_detection is True
    assert a.matched is False
    assert a.source_id is None
    # The Y dwarf is invisible in Gaia optical bands, so no physicals derive.
    assert a.distance_pc is None
    assert a.parallax_mas is None


def test_wise_0855_d1_d4_coverage_mask(sources) -> None:
    rec = sources["WISE_0855"]
    bands = rec.readings.spectral_bands

    # Detectors D1–D4 (< 3.8 um) are NOT covered; D5–D6 (3.8–5.0 um) ARE.
    by_detector: dict[str, list[bool]] = {}
    for b in bands:
        by_detector.setdefault(b.band_name, []).append(b.covered)

    for det in ("D1", "D2", "D3", "D4"):
        assert det in by_detector, f"missing detector {det}"
        assert all(c is False for c in by_detector[det]), (
            f"{det} must be fully uncovered for WISE 0855 (optical-invisible)"
        )
    for det in ("D5", "D6"):
        assert det in by_detector, f"missing detector {det}"
        assert all(c is True for c in by_detector[det]), (
            f"{det} must be fully covered for WISE 0855 (IR detection)"
        )


def test_wise_0855_refuses_h2o_ch4_on_coverage(readings) -> None:
    h2o = readings["WISE_0855"]["H2O"]
    ch4 = readings["WISE_0855"]["CH4"]

    # With D1–D4 uncovered, fewer than 3 bands cover the H2O (3.05 um) and
    # CH4 (3.20–3.65 um) features -> the engine must refuse them cleanly.
    assert h2o.value is None
    assert h2o.refusal_reason == "Not measured: fewer than three bands cover the feature"
    assert ch4.value is None
    assert ch4.refusal_reason == "Not measured: fewer than three bands cover the feature"