"""Acceptance tests for the NEW UI pass: close-up rendering, the share flow,
molecule readings, the API adapter, and cache busting.

Every assertion maps to a rule in docs/PROJECT-CONTEXT.md:

* section 10.3 — the four zoom levels and the 4x upsampled Source view
* section 10.1.7 — honest images
* section 5.4 / 9.7 — a missing reading is ``not measured`` with its reason
* section 5.3 — "Estimate" is reserved for model output
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
PW = BACKEND / "pw"


@pytest.fixture(scope="module")
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Section 10.3 / 10.1.7 — close-up rendering
# ---------------------------------------------------------------------------


def test_closeup_module_declares_two_renderings() -> None:
    from app.physics import closeup

    assert set(closeup.MODES) == {"raw", "enhanced"}
    assert closeup.MODES["raw"]["oversample"] == 1
    assert closeup.MODES["enhanced"]["oversample"] == 4
    assert closeup.MODES["raw"]["origin"] == "Measured"
    assert closeup.MODES["enhanced"]["origin"] == "Estimated"


def test_source_and_pixel_levels_get_the_oversampled_rendering() -> None:
    from app.physics import closeup

    assert closeup.mode_for_zoom("sky")["mode"] == "raw"
    assert closeup.mode_for_zoom("field")["mode"] == "raw"
    assert closeup.mode_for_zoom("source")["mode"] == "enhanced"
    assert closeup.mode_for_zoom("pixel")["mode"] == "enhanced"


def test_closeup_pixel_scale_is_a_quarter_of_the_native_pixel() -> None:
    from app.physics import closeup

    assert closeup.PIXEL_ARCSEC == 6.15
    assert closeup.mode_for_zoom("source")["pixel_arcsec"] == 6.15 / 4


def test_closeup_endpoint_returns_the_raw_frame_at_field_zoom(client: TestClient) -> None:
    r = client.get("/api/v1/cutout/epsindi/EPSB", params={"zoom": "field"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "raw"
    assert body["origin"] == "Measured"
    assert body["oversample"] == 1
    assert len(body["native"]["values"]) == body["size_native"] ** 2


def test_closeup_endpoint_returns_four_times_the_samples_at_source_zoom(client: TestClient) -> None:
    r = client.get("/api/v1/cutout/epsindi/EPSB", params={"zoom": "source", "size": 16})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "enhanced"
    assert body["origin"] == "Estimated"
    assert body["oversample"] == 4
    assert body["size_render"] == body["size_native"] * 4
    assert len(body["grid"]["values"]) == body["size_render"] ** 2
    assert len(body["native"]["values"]) == body["size_native"] ** 2


def test_oversampled_grid_bins_back_to_the_native_frame(client: TestClient) -> None:
    """The close-up must not invent light: averaging a 4x4 block returns the raw value."""
    r = client.get("/api/v1/cutout/epsindi/EPSB", params={"zoom": "source", "size": 8})
    body = r.json()
    os_factor = body["oversample"]
    fine = body["grid"]["values"]
    native = body["native"]["values"]
    n = body["size_native"]
    for row in range(n):
        for col in range(n):
            block = [
                fine[(row * os_factor + dy) * n * os_factor + (col * os_factor + dx)]
                for dy in range(os_factor)
                for dx in range(os_factor)
            ]
            mean = sum(block) / len(block)
            assert abs(mean - native[row * n + col]) < 0.01, (row, col, mean)


def test_closeup_keeps_the_flux_of_the_native_frame(client: TestClient) -> None:
    """Binning takes a mean, so the kernel must be scaled by os**2 or the close-up dims.

    Without the scale the oversampled peak came out 16x below the raw peak, which
    would have shown a dimmer source the moment a person zoomed in.  The remaining
    shortfall is the PSF wings that fall outside the cutout: this source sits on the
    field corner, so part of its light is off-grid by construction.  The test pins
    the bug (a 1/16 dimming) without pretending the edge truncation is zero.
    """
    raw = client.get("/api/v1/cutout/epsindi/EPSB", params={"zoom": "field", "size": 8}).json()
    cut = client.get("/api/v1/cutout/epsindi/EPSB", params={"zoom": "source", "size": 8}).json()
    raw_peak = max(v for v in raw["native"]["values"] if v is not None)
    cut_peak = max(v for v in cut["native"]["values"] if v is not None)
    assert raw_peak > 0
    ratio = cut_peak / raw_peak
    # a 1/16 dimming would be 0.0625; edge truncation leaves most of the flux
    assert ratio > 0.5, (raw_peak, cut_peak, ratio)
    assert ratio <= 1.05, (raw_peak, cut_peak, ratio)


def test_closeup_names_the_real_eosf_geometry() -> None:
    from app.physics import closeup

    assert closeup.EPSF_CELLS == 33
    assert closeup.EPSF_OVERSAMPLE == 5


def test_closeup_never_claims_super_resolution() -> None:
    source = (BACKEND / "app" / "physics" / "closeup.py").read_text(encoding="utf-8").lower()
    for banned in ("super-resolv", "superresolv", "hallucinat"):
        assert banned not in source


def test_unknown_field_is_a_404_with_a_next_step(client: TestClient) -> None:
    r = client.get("/api/v1/cutout/nosuchfield/X", params={"zoom": "source"})
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "SPHEREx has no prepared frames" in detail
    assert "Ready-made" in detail or "ready-made" in detail


def test_unknown_zoom_is_rejected_with_the_allowed_values(client: TestClient) -> None:
    r = client.get("/api/v1/cutout/epsindi/Epsilon_Indi_B", params={"zoom": "banana"})
    assert r.status_code == 422
    assert "sky, field, source or pixel" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Section 5.4 / 9.7 — molecule readings are never blank and never invented
# ---------------------------------------------------------------------------


def test_molecule_rows_always_cover_the_four_features() -> None:
    """The interface's own row builder must always return the four section 9.3 features."""
    explore = (PW / "explore.js").read_text(encoding="utf-8")
    assert "PW.molRows=function" in explore
    for name in ("Water ice", "Methane", "Carbon dioxide", "Carbon monoxide"):
        assert name in explore, name


def test_a_missing_molecule_reading_carries_a_reason() -> None:
    explore = (PW / "explore.js").read_text(encoding="utf-8")
    assert "not measured" in explore
    assert "no reading for this source yet" in explore


def test_adapter_never_replaces_a_populated_block_with_nothing() -> None:
    api = (PW / "api.js").read_text(encoding="utf-8")
    assert "if(rows)c.mol=rows;" in api
    assert "if(S&&rows&&rows.length){S.mol=rows;changed=true}" in api


def test_adapter_maps_backend_readings_onto_the_four_features() -> None:
    api = (PW / "api.js").read_text(encoding="utf-8")
    for mol in ("H2O", "CH4", "CO2", "CO"):
        assert mol + ":" in api, mol
    assert "refusal_reason" in api


# ---------------------------------------------------------------------------
# The API adapter: the interface is wired to the backend
# ---------------------------------------------------------------------------


def test_adapter_is_loaded_after_the_interface() -> None:
    html = (BACKEND / "index.html").read_text(encoding="utf-8")
    assert "pw/api.js" in html
    assert html.index("pw/pages.js") < html.index("pw/api.js")


def test_adapter_calls_every_backend_surface() -> None:
    api = (PW / "api.js").read_text(encoding="utf-8")
    for path in (
        "/api/v1/finds",
        "/api/ml/predict/",
        "/api/v1/targets/",
        "/api/v1/cutout/",
    ):
        assert path in api, path
    for verb in ("/vote", "/comment", "/assign", "/decide"):
        assert verb in api, verb


def test_adapter_wires_the_ml_outputs() -> None:
    api = (PW / "api.js").read_text(encoding="utf-8")
    for field in ("preal", "best", "runner", "novel", "prio", "tags", "deciding_bands"):
        assert field in api, field


def test_adapter_uses_the_4x_closeup() -> None:
    api = (PW / "api.js").read_text(encoding="utf-8")
    assert "PW.prefetchCutout" in api
    assert "'source'" in api
    assert "voCU" in api


# ---------------------------------------------------------------------------
# "Share your find" — a real button, never a jump to a blank map
# ---------------------------------------------------------------------------


def test_share_button_is_a_button_not_a_link() -> None:
    pages = (PW / "pages.js").read_text(encoding="utf-8")
    assert 'id="dShare"' in pages
    assert not re.search(r'href="#/explore"[^>]*>Share your find', pages)


def test_share_modal_does_not_send_a_guest_away() -> None:
    api = (PW / "api.js").read_text(encoding="utf-8")
    share = api.split("PW.shareFind=function", 1)[1].split("/* ---------- target selector", 1)[0]
    assert "location.hash='#/signin'" not in share
    assert "Citizen Explorer" in share


def test_submit_lands_on_the_new_discussion() -> None:
    api = (PW / "api.js").read_text(encoding="utf-8")
    assert "location.hash=target" in api
    assert 'a[href^="#/discussions/"]' in api


def test_share_modal_offers_a_target_selector() -> None:
    api = (PW / "api.js").read_text(encoding="utf-8")
    assert "Choose a target" in api
    assert "optgroup" in api


# ---------------------------------------------------------------------------
# Cache busting
# ---------------------------------------------------------------------------


def test_store_key_is_new1() -> None:
    core = (PW / "core.js").read_text(encoding="utf-8")
    assert "var KEY='pw-new1'" in core


def test_index_html_uses_new1() -> None:
    html = (BACKEND / "index.html").read_text(encoding="utf-8")
    for asset in (
        "pw/app.css?v=new1",
        "pw/core.js?v=new1",
        "pw/sky.js?v=new1",
        "pw/explore.js?v=new1",
        "pw/pages.js?v=new1",
        "pw/api.js?v=new1",
    ):
        assert asset in html, asset
    assert "?v=9" not in html


def test_stale_store_keys_are_purged() -> None:
    html = (BACKEND / "index.html").read_text(encoding="utf-8")
    assert "pw-stale-purge" in html
    for stale in ("pw-v5", "pw-v6", "pw-v7", "pw-v8", "pw-v9"):
        assert stale in html, stale


def test_app_shell_is_served_no_store(client: TestClient) -> None:
    for path in ("/", "/pw/core.js", "/pw/api.js"):
        r = client.get(path)
        assert r.status_code == 200, path
        header = r.headers.get("cache-control", "")
        assert "no-store" in header, (path, header)


# ---------------------------------------------------------------------------
# The NEW UI is the only frontend served
# ---------------------------------------------------------------------------


def test_new_ui_is_the_served_frontend(client: TestClient) -> None:
    html = client.get("/").text
    assert "pw/sky.js" in html, "the NEW UI loads sky.js"
    assert "pw/api.js" in html


def test_old_ui_is_not_served(client: TestClient) -> None:
    pages = client.get("/pw/pages.js").text
    assert "openShareModal" not in pages
    assert "btnShareDisc" not in pages
    assert client.get("/_old_ui_backup/pw/core.js").status_code == 404


# ---------------------------------------------------------------------------
# The rest of the API still works
# ---------------------------------------------------------------------------


def test_existing_endpoints_still_answer(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/api/v1/manifest").status_code == 200
    assert isinstance(client.get("/api/v1/finds").json(), list)
    r = client.get("/api/ml/predict/epsindi/EPSB")
    assert r.status_code == 200
    body = r.json()
    assert body["preal"] is not None
    assert isinstance(body["best"], list) and len(body["best"]) == 2
    assert body["prio"] is not None


def test_target_endpoint_returns_the_four_molecules_and_102_bands(client: TestClient) -> None:
    body = client.get("/api/v1/targets/Epsilon_Indi_B").json()
    readings = body["molecules"]["readings"]
    assert len(readings) == 4
    assert all("refusal_reason" in r for r in readings)
    assert len(body["readings"]["spectral_bands"]) == 102
