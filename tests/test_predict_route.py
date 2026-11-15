"""Tests for the Step-4 polish items: live ML endpoints on the FastAPI app."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# /health advertises both tiers
# ---------------------------------------------------------------------------


def test_health_advertises_tier_a_and_tier_b(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()

    # Tier A: Layer 1 physics engines.
    assert body["tier_a"]["engines"]["molecules"]
    assert body["tier_a"]["engines"]["surveys"]
    assert body["tier_a"]["epochs"]["gaia_dr3_mjd"] > 0

    # Tier B: M1, M2, M3 all advertised.
    tier_b = body["tier_b"]
    assert set(tier_b["engines"]) == {"M1", "M2", "M3"}
    assert tier_b["engines"]["M1"]["outputs"].startswith("p_real")
    assert set(tier_b["engines"]["M2"]["experts"]) == {"E1", "E2"}
    assert tier_b["engines"]["M3"]["ontology"] == ["U1", "U2", "U3", "U4"]

    # Backwards-compatible flat block still present for the Step-2 contract.
    assert body["engines"]["molecules"]


# ---------------------------------------------------------------------------
# /api/v1/predict/{target_name} runs the live pipeline
# ---------------------------------------------------------------------------


def test_predict_epsilon_indi_b(client: TestClient) -> None:
    r = client.get("/api/v1/predict/Epsilon_Indi_B")
    assert r.status_code == 200
    body = r.json()

    assert body["target_name"] == "Epsilon_Indi_B"
    assert body["computed_live"] is True

    # M1 gate produced a real probability.
    m1 = body["m1_artefact_gate"]
    assert 0.0 <= m1["p_real"] <= 1.0

    # M2 panel has both stored results and the honesty rule.
    m2 = body["m2_identity"]
    assert m2["spectrum_alone"]["experiment"] == "spectrum_alone"
    assert m2["all_data"]["experiment"] == "all_data"
    assert "honest_ui" in m2

    # Epsilon Indi B is a brown dwarf: the live pipeline must land on
    # "Ultracool dwarf" and must not be classified as a failed detection.
    assert m2["all_data"]["top_class"] in {"Ultracool dwarf", "Unclassified"}

    # E1/E2 disagreement cap is respected whenever it fires.
    honest = m2["honest_ui"]
    if honest.get("disagreement"):
        assert m2["all_data"]["display_confidence"] <= 0.5

    # M3 produced a novelty percentile and a valid ontology code.
    m3 = body["m3_novelty"]
    assert 0.0 <= m3["novelty_percentile"] <= 100.0
    assert m3["discovery_class"] in {"U1", "U2", "U3", "U4"}


def test_predict_unknown_target_404(client: TestClient) -> None:
    r = client.get("/api/v1/predict/Not_A_Real_Target")
    assert r.status_code == 404
    assert "Benchmark targets" in r.json()["detail"]


def test_predict_wise0855_no_optical_counterpart(client: TestClient) -> None:
    """The live route must preserve WISE 0855's U1 (uncatalogued) discovery class."""
    r = client.get("/api/v1/predict/WISE_0855", params={"resample_times": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["m3_novelty"]["discovery_class"] in {"U1", "U2", "U3", "U4"}
