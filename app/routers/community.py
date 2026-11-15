"""Pillar 3/4 — community finds store for the SPA frontend.

The vanilla-JS frontend keeps its local ``SEED.finds`` as a fallback. This router
is the single backend source of truth for community submissions: creating a find,
withdrawing/deleting it, posting comments (with frame tags), casting up/down
votes (status flips to ``Queued`` at ``need`` up-votes), Lab assign/unassign, and
the scientist Accept/Close decision that feeds the public catalog.

Persistence is a JSON file (``sample_packs/finds.json``) written on every
mutation, mirroring ``app/routers/cases.py``.  It starts empty so the frontend's
seed data is used until a user actually shares something.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

BACKEND_DIR = Path(__file__).resolve().parents[2]
FINDS_FILE = BACKEND_DIR / "sample_packs" / "finds.json"

router = APIRouter(prefix="/api/v1/finds", tags=["citizen-science"])

_lock = threading.Lock()

# Statuses mirror the frontend PW.STATUS ladder (Draft is client-only).
STATUSES = {"Needs votes", "Queued", "In review", "Accepted", "Closed", "Withdrawn"}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def _load() -> list[dict[str, Any]]:
    if not FINDS_FILE.exists():
        return []
    try:
        return json.loads(FINDS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save(finds: list[dict[str, Any]]) -> None:
    FINDS_FILE.write_text(json.dumps(finds, indent=2), encoding="utf-8")


def _find(finds: list[dict[str, Any]], find_id: str) -> dict[str, Any]:
    for f in finds:
        if f["id"] == find_id:
            return f
    raise HTTPException(status_code=404, detail=f"Unknown find '{find_id}'.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: str
    text: str


class FindIn(BaseModel):
    """A community submission from the Sky Explorer."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: str
    source: str = "Community"
    finder: Optional[str] = None
    status: str = "Needs votes"
    field: str
    src: str
    notes: str


class VoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: int = Field(ge=-1, le=1, description="+1 up, -1 down")
    user: str


class AssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: Optional[str] = None


class DecideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str = Field(description="Accepted | Closed")
    reason: Optional[str] = None
    comment: Optional[str] = None
    reviewer: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
def list_finds() -> list[dict[str, Any]]:
    """All finds.  The frontend hydrates its store from this; empty => seed data."""
    return _load()


@router.post("", status_code=201)
def create_find(find: FindIn) -> dict[str, Any]:
    with _lock:
        finds = _load()
        if any(f["id"] == find.id for f in finds):
            raise HTTPException(status_code=409, detail=f"Find '{find.id}' already exists.")
        record = find.model_dump()
        record["up"] = 0
        record["down"] = 0
        record["need"] = 10
        record["made"] = "15 Nov 2026"
        record["comments"] = []
        record["mine"] = True
        finds.insert(0, record)
        _save(finds)
    return record


@router.post("/{find_id}/comment")
def add_comment(find_id: str, comment: CommentIn) -> dict[str, Any]:
    with _lock:
        finds = _load()
        f = _find(finds, find_id)
        f.setdefault("comments", []).append(
            {"by": comment.by, "at": "15 Nov 2026", "text": comment.text}
        )
        _save(finds)
    return f


@router.post("/{find_id}/vote")
def vote(find_id: str, vote: VoteIn) -> dict[str, Any]:
    with _lock:
        finds = _load()
        f = _find(finds, find_id)
        if f["status"] != "Needs votes":
            raise HTTPException(status_code=409, detail=f"Voting closed (status: {f['status']}).")
        if vote.direction == 1:
            f["up"] += 1
            if f["up"] >= f.get("need", 10):
                f["status"] = "Queued"
        elif vote.direction == -1:
            f["down"] += 1
        _save(finds)
    return f


@router.delete("/{find_id}")
def delete_find(find_id: str) -> dict[str, Any]:
    with _lock:
        finds = _load()
        f = _find(finds, find_id)
        if not f.get("up") and not f.get("down") and not f.get("comments"):
            finds = [x for x in finds if x["id"] != find_id]
        else:
            f["status"] = "Withdrawn"
        _save(finds)
    return {"id": find_id, "status": f.get("status", "deleted")}


@router.post("/{find_id}/assign")
def assign(find_id: str, body: AssignIn) -> dict[str, Any]:
    with _lock:
        finds = _load()
        f = _find(finds, find_id)
        if body.reviewer:
            f["status"] = "In review"
            f["reviewer"] = body.reviewer
        else:
            f["status"] = "Queued"
            f["reviewer"] = None
        _save(finds)
    return f


@router.post("/{find_id}/decide")
def decide(find_id: str, body: DecideIn) -> dict[str, Any]:
    with _lock:
        finds = _load()
        f = _find(finds, find_id)
        if body.decision not in ("Accepted", "Closed"):
            raise HTTPException(status_code=400, detail="decision must be Accepted or Closed.")
        f["status"] = body.decision
        f["reviewer"] = body.reviewer
        if body.decision == "Closed":
            f["reason"] = body.reason or "Closed by reviewer"
        if body.comment:
            f.setdefault("comments", []).append(
                {"by": f"{body.reviewer}, Verified scientist", "at": "15 Nov 2026", "text": body.comment}
            )
        if body.decision == "Accepted":
            f.setdefault("tags", []).append("Ready to report")
        _save(finds)
    return f