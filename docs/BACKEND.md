# Phantom Worlds — Backend

Backend & ML engine for **"Phantom Worlds"** (NASA Space Apps Challenge 2026).

Two tiers:

- **Tier A — Layer 1 physics** (`app/physics/`): 102-band SPHEREx spectrophotometry,
  molecule readings with Monte Carlo error propagation, Gaia cone-search
  cross-matching, parallax astrometry, and physical gates.
- **Tier B — Machine learning** (`app/ml/`): M1 artefact gate, M2 two-level type
  classifier (E1 template matcher + E2 trees + Layer 3 combiner), and M3 novelty /
  anomaly detector with the U1–U4 discovery ontology.

The reference specification is `phantom-worlds-ml-research.md` (Sections 3–9, 13).

---

## Requirements

- Windows (the physics path sets `OPENBLAS_NUM_THREADS=1` before importing numpy)
- [`uv`](https://docs.astral.sh/uv/) — this project **must** use `uv`, never `pip`

```powershell
uv venv .venv
uv pip install -r requirements.txt
```

> `OPENBLAS_NUM_THREADS=1` is mandatory. It is set inside `app/__init__.py`,
> `app/ml/__init__.py`, `app/main.py`, `tests/conftest.py` and the report-card
> script; if you run numpy directly you must export it yourself.

---

## Run the API

```powershell
$env:OPENBLAS_NUM_THREADS="1"
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs for the interactive OpenAPI page.

The M1–M3 stack is trained **lazily**: the first call to an ML endpoint takes
~30 s (it builds and fits the synthetic corpus), then it is cached for the rest
of the process.

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness + capability check. Reports **Tier A** physics engines and **Tier B** M1/M2/M3 status. |
| `GET` | `/api/v1/sky` | Cone search over benchmark targets + Gaia field stars (`ra`, `dec`, `fov`, `target_name`). |
| `GET` | `/api/v1/targets/{target_name}` | Layer 1 payload for one benchmark target (molecules recomputed by `MoleculeEngine`). |
| `GET` | `/api/v1/predict/{target_name}` | **Live** M1 → M2 → M3 pipeline run for one target (see below). |
| `POST` | `/api/v1/cron/ingest` | Simulated SPHEREx archive update pipeline (idempotent diff vs frozen pack). |
| `GET` | `/api/v1/cases` | Citizen-science case list (Pillar 3/4). |
| `POST` | `/api/v1/cases/{case_id}/vote` | Blind review vote; unlocks forum only after the blind vote. |
| `GET` | `/api/v1/cases/{case_id}/export/{format}` | Export packet: `backyard_worlds`, `aavso_vsx`, `mpc_ades`. |
| `GET` | `/api/v1/manifest` | Bundle metadata for the frontend. |

### `/api/v1/predict/{target_name}`

Runs the full live pipeline and returns:

```jsonc
{
  "target_name": "Epsilon_Indi_B",
  "computed_live": true,
  "m1_artefact_gate": { "p_real": 0.99, "is_artefact": false, ... },
  "m2_identity": {
    "spectrum_alone": { "experiment": "spectrum_alone", "top_class": "...", ... },
    "all_data":      { "experiment": "all_data",      "top_class": "...", ... },
    "honest_ui": { ... }
  },
  "m3_novelty": {
    "novelty_percentile": 77.0, "is_novel": true, "discovery_class": "U2", ...
  }
}
```

Query params: `resample_times` (0–500, default 100 — the 100× spectrum resampling
within flux errors for the confidence range; `0` disables) and `epoch_mjd` for the
astrometry fed to experts E4–E7.

> This differs from `/api/v1/targets/{name}`, which serves the **frozen**
> Step-1 identity panel. `/predict` re-executes M1/M2/M3 on demand from the real
> 102-band spectrum and cross-survey flags.

---

## Benchmark report card

```powershell
$env:OPENBLAS_NUM_THREADS="1"
.\.venv\Scripts\python.exe -m scripts.generate_report_card
```

Regenerates `BENCHMARK_REPORT_CARD.md`, `sample_packs/benchmark_report.json`, and
rewrites the identity blocks in `sample_packs/sources.json` + `cases.json` with
real M1–M3 outputs.

The five benchmark targets: `Barnards_Star`, `Epsilon_Indi_B`, `R_Draconis`,
`RW_Aurigae`, `WISE_0855`.

---

## Tests

```powershell
$env:OPENBLAS_NUM_THREADS="1"
$env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe -m pytest tests -q
```

- `tests/test_tier_a.py` — Layer 1 physics + FastAPI (11 tests)
- `tests/test_tier_b.py` — M1/M2/M3, citizen-science cases, report card (19 tests)
- `tests/test_predict_route.py` — live `/health` + `/api/v1/predict` (4 tests)

---

## Honesty commitments (from `phantom-worlds-ml-research.md`)

- Every number carries an `origin` (`Measured` / `Catalogue` / `Estimated` / `Assumed`).
- Refused molecule readings always state a reason.
- E1/E2 top-class disagreement caps displayed confidence at 50%; below 50% or an
  empty conformal set ⇒ `Unclassified`.
- The training corpus is **synthetic**; the SPIFF Zenodo / SPLICES ingestion path
  (`app/ml/dataset.py::append_external`) is a stub. No external-validated accuracy
  is claimed.
- `shap` is not installed, so `deciding_bands` uses the documented tree-importance
  fallback.

---

## Layout

```
app/
  physics/     Tier A: molecules.py, surveys.py
  ml/          Tier B: dataset, features, m1_artefact, m2_classifier,
               m3_novelty, templates, pipeline, constants
  routers/     Pillar 3/4 citizen-science cases
  main.py      FastAPI app + routes
  schemas.py   Pydantic v2 models (Layer 1/2/3, cases, export packets)
scripts/       generate_report_card.py
tests/         tier_a, tier_b, predict_route
sample_packs/  sources.json, cases.json, manifest.json, benchmark_report.json
```
