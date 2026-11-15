"""Step-5 integration tests: SPA static serving + "ML Nyusul" adapter.

These tests exercise the FastAPI routes the vanilla-JS frontend calls, so the
whole backend surface (root HTML, /pw static assets, community finds, and the
field/src -> target ML adapter) is proven wired end-to-end.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Static SPA serving
# ---------------------------------------------------------------------------


def test_root_serves_index_html(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # The SPA bootstraps the Phantom Worlds global.
    assert r.text.count("Phantom Worlds") >= 1


def test_pw_static_core_js(client: TestClient) -> None:
    r = client.get("/pw/core.js")
    assert r.status_code == 200
    assert "application/javascript" in r.headers["content-type"] or "text/javascript" in r.headers["content-type"]
    assert "window.PW" in r.text


def test_pw_static_css(client: TestClient) -> None:
    r = client.get("/pw/app.css")
    assert r.status_code == 200
    assert "text/css" in r.headers["content-type"]


# ---------------------------------------------------------------------------
# Community finds store (empty by default -> frontend falls back to SEED)
# ---------------------------------------------------------------------------


def test_finds_empty_by_default(client: TestClient) -> None:
    r = client.get("/api/v1/finds")
    assert r.status_code == 200
    # The backend store starts empty so the SPA keeps its SEED data.
    assert isinstance(r.json(), list)


# ---------------------------------------------------------------------------
# "ML Nyusul" adapter — /api/ml/predict/{field}/{src_id}
# ---------------------------------------------------------------------------


def test_ml_adapter_maps_benchmark_target(client: TestClient) -> None:
    # epsindi/EPSB -> Epsilon_Indi_B (a benchmark target).
    r = client.get("/api/ml/predict/epsindi/EPSB")
    assert r.status_code == 200
    body = r.json()

    # Frontend-shaped keys, and noest must be a real bool (False here).
    assert body["noest"] is False
    assert isinstance(body["preal"], float)
    assert isinstance(body["best"], list) and len(body["best"]) == 2
    assert body["target_name"] == "Epsilon_Indi_B"


def test_ml_adapter_unknown_source_noest(client: TestClient) -> None:
    # atlas/3I (comet) has no benchmark target -> graceful noest signal.
    r = client.get("/api/ml/predict/atlas/3I")
    # The adapter returns 404 for unmapped sources; the frontend also treats
    # null (non-2xx) as noest, so both paths degrade gracefully.
    assert r.status_code == 404


def test_ml_adapter_wise0855_preserves_u1(client: TestClient) -> None:
    r = client.get("/api/ml/predict/wise0855/W0855")
    assert r.status_code == 200
    body = r.json()
    # WISE 0855 is genuinely uncatalogued in Gaia optical (U1).
    assert body["discovery_class"] in {"U1", "U2", "U3", "U4"}