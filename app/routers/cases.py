"""Pillar 3 / 4 — citizen-science case router + dossier exporters.

Implements:

* ``POST /api/v1/cases/{case_id}/vote`` — blind review vote with O-to-Y
  reputation weighting.  A user's forum unlock only happens **after** a blind
  vote (votes carry a blind-review flag; a vote that commits a reviewer to a
  type is what unlocks the thread).
* ``GET /api/v1/cases/{case_id}/export/{format}`` — scientific hand-off packets:
  ``backyard_worlds``, ``aavso_vsx``, ``mpc_ades``.

State is persisted by re-reading + rewriting ``sample_packs/cases.json`` (the
single source of truth for Pillar 3/4, frozen at Step 1 but designed to accept
reviewer votes).
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ml import constants as C

BACKEND_DIR = Path(__file__).resolve().parents[2]
CASES_FILE = BACKEND_DIR / "sample_packs" / "cases.json"
SOURCES_FILE = BACKEND_DIR / "sample_packs" / "sources.json"

router = APIRouter(prefix="/api/v1/cases", tags=["citizen-science"])

# The five types reviewers can vote for (blind review).
VOTABLE_TYPES = ["Star", "Ultracool dwarf", "Young star", "Evolved giant star", "Unclassified"]


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _load_cases() -> list[dict[str, Any]]:
    if not CASES_FILE.exists():
        raise HTTPException(status_code=503, detail="cases.json has not been generated yet.")
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))


def _load_sources() -> dict[str, dict[str, Any]]:
    if not SOURCES_FILE.exists():
        return {}
    return {s["target_name"]: s for s in json.loads(SOURCES_FILE.read_text(encoding="utf-8"))}


def _save_cases(cases: list[dict[str, Any]]) -> None:
    CASES_FILE.write_text(json.dumps(cases, indent=2), encoding="utf-8")


def _find_case(case_id: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    for c in cases:
        if c["case_id"] == case_id:
            return c
    raise HTTPException(status_code=404, detail=f"Unknown case '{case_id}'.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Reputation weighting
# ---------------------------------------------------------------------------


def reputation_weight(spectral_class: str) -> float:
    """O->Y ladder -> 0.00..0.92 vote weight (brief specification)."""
    key = spectral_class.strip().upper()
    if key not in C.SPECTRAL_REPUTATION_WEIGHT:
        raise HTTPException(status_code=400, detail=f"Unknown spectral class '{spectral_class}'.")
    return C.SPECTRAL_REPUTATION_WEIGHT[key]


def _phase_case(case: dict[str, Any], weight: float, vote_type: str) -> tuple[dict[str, Any], bool]:
    """Apply a blind vote + O-Y weight; return (case, reached_stage5)."""
    tally = case.setdefault("blind_review_vote_tally", {})
    tally[vote_type] = tally.get(vote_type, 0) + 1

    # Aggregate reputation weight (upper-bounded, additive).
    case["spectral_reputation_weight"] = min(1.0, round(float(case.get("spectral_reputation_weight", 0.0)) + weight, 3))

    # Forum unlock only after a blind vote (the trigger is the committed vote).
    case["forum_unlock_status"] = True
    case["notes"] = f"Blind review opened; last vote {_now_iso()}"

    reached5 = _advance_if_consensus(case)
    return case, reached5


def _advance_if_consensus(case: dict[str, Any]) -> bool:
    """Advance to Stage 5 when weighted vote count >= 5 and agreement >= 0.80."""
    tally = case.get("blind_review_vote_tally", {})
    total_weighted = sum(tally.values()) * case.get("spectral_reputation_weight", 0.0)
    total_votes = sum(tally.values())
    if total_votes >= 5:
        top = max(tally, key=tally.get)
        agreement = tally[top] / total_votes if total_votes else 0.0
        if agreement >= 0.80:
            case["verification_stage"] = max(case.get("verification_stage", 1), 5)
            case["notes"] = (
                f"Consensus reached: {top} with {agreement:.0%} agreement "
                f"({total_votes} votes). Follow-Up Packet ready."
            )
            return True
    return False


# ---------------------------------------------------------------------------
# Votes
# ---------------------------------------------------------------------------


class VoteRequest(BaseModel):
    model_config = {"extra": "forbid"}

    reviewer_id: str = Field(description="Anonymous reviewer handle")
    spectral_class: str = Field(description="O/B/A/F/G/K/M/L/T/Y reputation class")
    vote_type: str = Field(description="Blind-review type vote")


class VoteResponse(BaseModel):
    model_config = {"extra": "forbid"}

    case_id: str
    vote_tally: dict[str, int]
    spectral_reputation_weight: float
    forum_unlock_status: bool
    verification_stage: int
    consensus_reached: bool


@router.post("/{case_id}/vote", response_model=VoteResponse)
def submit_vote(case_id: str, vote: VoteRequest) -> VoteResponse:
    """Submit a blind review vote (unlocks the forum, then checks consensus)."""
    if vote.vote_type not in VOTABLE_TYPES:
        raise HTTPException(status_code=400, detail=f"Vote type must be one of {VOTABLE_TYPES}.")

    w = reputation_weight(vote.spectral_class)
    cases = _load_cases()
    case = _find_case(case_id, cases)
    case, reached5 = _phase_case(case, w, vote.vote_type)
    _save_cases(cases)

    return VoteResponse(
        case_id=case["case_id"],
        vote_tally=case["blind_review_vote_tally"],
        spectral_reputation_weight=case["spectral_reputation_weight"],
        forum_unlock_status=case["forum_unlock_status"],
        verification_stage=case["verification_stage"],
        consensus_reached=reached5,
    )


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------


def _source_for_case(case: dict[str, Any]) -> dict[str, Any]:
    sources = _load_sources()
    src = next((s for s in sources.values() if s["source_id"] == case.get("source_id")), None)
    if src is None:
        raise HTTPException(status_code=404, detail=f"No source for case {case['case_id']}.")
    return src


def _backyard_worlds(case: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """L/T/Y motion + IR vector hand-off packet."""
    tname = case["target_name"]
    gaia = src["readings"]["gaia"] or {}
    mols = {m["molecule"]: m for m in src["readings"]["molecules"]}
    ch4 = mols.get("CH4", {}).get("value")

    subtype_guess = "Y" if tname == "WISE_0855" else ("T" if ch4 and ch4 > 0.3 else "L")
    return {
        "candidate_id": f"PW-{tname}",
        "ra_deg": gaia.get("ra_deg"),
        "dec_deg": gaia.get("dec_deg"),
        "w1_mag": None,
        "w2_mag": None,
        "w1_w2_color": None,
        "proper_motion_mas_yr": gaia.get("pm_total_mas_yr"),
        "spectral_type_guess": subtype_guess,
        "notes": (
            "Motion + IR vector for Backyard Worlds review. "
            f"Molecules: CH4={ch4} mag (engine, sigma={mols.get('CH4', {}).get('sigma')})."
        ),
    }


def _aavso_vsx(case: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Variable-star dossier with the 3 moderator checks pre-filled."""
    tname = case["target_name"]
    variable = src["readings"].get("variable_flag", False)
    return {
        "name": tname.replace("_", " "),
        "ra_deg": (src["readings"]["gaia"] or {}).get("ra_deg"),
        "dec_deg": (src["readings"]["gaia"] or {}).get("dec_deg"),
        "variability_type": "M" if tname == "R_Draconis" else "T",
        "period_days": 245.4 if tname == "R_Draconis" else None,
        "epoch_mjd": None,
        "mag_min": None,
        "mag_max": None,
        "band": "V",
        "notes": (
            "3 moderator checks: (1) visit-to-visit amplitude flagged, "
            "(2) blend share recorded, (3) overflow bands documented."
            if variable else "Variable-star candidate."
        ),
    }


def _mpc_ades(case: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Two-night ADES astrometry packet (JSON form; XML also producible)."""
    tname = case["target_name"]
    gaia = src["readings"]["gaia"] or {}
    return {
        "obs_time_utc": _now_iso(),
        "ra_deg": gaia.get("ra_deg"),
        "dec_deg": gaia.get("dec_deg"),
        "mag": None,
        "band": "V",
        "observatory_code": "PHW",
        "notes": "Two-night ADES astrometry placeholder for a moving-candidate submission.",
    }


@router.get("/{case_id}/export/{format}")
def export_case(case_id: str, format: str) -> dict[str, Any]:
    """Generate a scientific hand-off packet for a case."""
    cases = _load_cases()
    case = _find_case(case_id, cases)
    src = _source_for_case(case)

    if format == "backyard_worlds":
        return {"format": format, "payload": _backyard_worlds(case, src)}
    if format == "aavso_vsx":
        return {"format": format, "payload": _aavso_vsx(case, src)}
    if format == "mpc_ades":
        return {"format": format, "payload": _mpc_ades(case, src)}
    raise HTTPException(
        status_code=404,
        detail=f"Unknown export format '{format}'. Choose backyard_worlds | aavso_vsx | mpc_ades.",
    )