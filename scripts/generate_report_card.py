"""Generate the 5-target benchmark report card.

Replaces the Step-1 placeholder Layer 2/3 numbers in ``sample_packs/sources.json``
and ``sample_packs/cases.json`` with real M1..M3 outputs, then writes
``BENCHMARK_REPORT_CARD.md`` and ``sample_packs/benchmark_report.json``.

This is the single entrypoint for the live pipeline update:
    python -m scripts.generate_report_card
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np

from app.ml import constants as C, dataset, m1_artefact, m3_novelty, pipeline
from app.ml.features import RealSurvey, SourceFeatures
from app.schemas import CaseRecord, SourceRecord

BASE = Path(__file__).resolve().parents[1]
PACK = BASE / "sample_packs"
SOURCES = PACK / "sources.json"
CASES = PACK / "cases.json"
REPORT_MD = BASE / "BENCHMARK_REPORT_CARD.md"
REPORT_JSON = PACK / "benchmark_report.json"

# Section 8's per-target expectation, verbatim.
EXPECTED: dict[str, str] = {
    "Barnards_Star": "Star, cool dwarf, no methane dip",
    "Epsilon_Indi_B": "Ultracool dwarf, T type, methane dip",
    "WISE_0855": "Ultracool dwarf Y, or Unclassified with a stated reason",
    "RW_Aurigae": "Young star, variable (blended pair)",
    "R_Draconis": "Evolved giant, variable (overflow)",
}


def _load() -> tuple[list[SourceRecord], list[dict[str, Any]]]:
    sources = [SourceRecord.model_validate(x) for x in json.loads(SOURCES.read_text(encoding="utf-8"))]
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    return sources, cases


def _survey_for(rec: SourceRecord) -> RealSurvey:
    cs = rec.cross_surveys
    return RealSurvey(
        gaia_match=cs.gaia_match,
        neowise_match=bool(cs.neowise_match),
        catwise_match=bool(cs.catwise_match),
        two_mass_match=bool(cs.two_mass_match),
        solar_system_object=cs.solar_system_object,
        simbad_type=cs.simbad_type,
        splices_class=cs.splices_class,
    )


def _assemble_report() -> dict[str, Any]:
    """Train M2/M3 and evaluate the five targets."""
    ds = dataset.generate_dataset()
    models = pipeline.train_models(ds)

    # M1 artefact gate.
    gate = m1_artefact.M1ArtefactGate()
    Xa, ya = ds.as_real_artefact()
    gate.fit(Xa, ya)

    # M3 novelty detector.
    det = m3_novelty.NoveltyDetector()
    det.fit(ds)

    sources, cases = _load()
    targets: list[dict[str, Any]] = []

    for rec in sources:
        r = rec.readings
        survey = _survey_for(rec)

        # M1 gate on the 102-band flux.
        flux = np.array([b.flux_mjy if (b.covered and b.flux_mjy is not None) else 0.0
                         for b in r.spectral_bands])
        err = np.array([b.flux_error_mjy if b.flux_error_mjy is not None else 1e-6
                        for b in r.spectral_bands])
        ver = gate.predict(flux, err)

        # M2 identity panel.
        panel = pipeline.predict_source(models, r, survey=survey)

        # M3 novelty + discovery.
        feats = SourceFeatures.from_readings(r, survey)
        e1 = models.matcher.match(
            feats.spectrum, feats.errors, models.class_templates
        )
        con_empty = not panel.all_data.conformal_set_90
        nov = det.evaluate(r, e1=e1, conformal_empty=con_empty, feats=feats)

        targets.append(
            {
                "target_name": rec.target_name,
                "artefact": {"p_real": round(ver.p_real, 4), "is_artefact": ver.is_artefact},
                "spectrum_alone": panel.spectrum_alone.model_dump(mode="json"),
                "all_data": panel.all_data.model_dump(mode="json"),
                "honest_ui": panel.honest_ui.model_dump(mode="json"),
                "novelty": {
                    "percentile": nov.novelty_percentile,
                    "is_novel": nov.is_novel,
                    "discovery_class": nov.discovery_class,
                    "reasons": nov.reasons,
                    "reduced_chi2": nov.reduced_chi2,
                },
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metrics": {k: round(v, 6) for k, v in models.metrics.items()},
        "pass_marks": C.PASS_MARKS,
        "targets": targets,
    }


def _update_pack(report: dict[str, Any]) -> None:
    """Replace the placeholder identity panels + case discovery classes."""
    sources, cases = _load()
    by_name = {t["target_name"]: t for t in report["targets"]}

    for s in sources:
        t = by_name[s.target_name]
        s.identity.spectrum_alone = s.identity.spectrum_alone.__class__.model_validate(t["spectrum_alone"])
        s.identity.all_data = s.identity.all_data.__class__.model_validate(t["all_data"])
        s.identity.honest_ui = s.identity.honest_ui.__class__.model_validate(t["honest_ui"])

    # Write updated sources.json.
    SOURCES.write_text(
        json.dumps([json.loads(s.model_dump_json()) for s in sources], indent=2),
        encoding="utf-8",
    )

    # Update case discovery classes from the all_data identity panel.
    for c in cases:
        t = by_name.get(c["target_name"])
        if t:
            c["discovery_class"] = t["all_data"]["discovery_class"]
    CASES.write_text(json.dumps(cases, indent=2), encoding="utf-8")


def _write_md(report: dict[str, Any]) -> None:
    metrics = report["metrics"]
    targets = report["targets"]
    lines: list[str] = []
    lines.append("# Phantom Worlds — 5-Target Benchmark Report Card\n")
    lines.append(f"Generated {report['generated_at']}\n")
    lines.append("This is the **live M1..M3 pipeline output** on the five benchmark targets. "
                 "It replaces the Step-1 Estimated placeholder numbers.\n")

    lines.append("## 1. Release gates (Section 9)\n")
    lines.append("| Metric | Value | Pass mark | Status |")
    lines.append("|---|---|---|---|")
    ba = metrics.get("all_data_balanced_accuracy", 0.0)
    ece = metrics.get("all_data_calibration_error", 1.0)
    lines.append(f"| Level-1 balanced accuracy (gold test, S/N>10) | {ba:.3f} | >= {C.PASS_MARKS['level1_recall']} | {'✅' if ba >= C.PASS_MARKS['level1_recall'] else '❌'} |")
    lines.append(f"| Calibration error (ECE) | {ece:.4f} | <= {C.PASS_MARKS['calibration_error_max']} | {'✅' if ece <= C.PASS_MARKS['calibration_error_max'] else '❌'} |")
    cov = metrics.get("all_data_conformal_coverage")
    if cov is None or not np.isfinite(cov):
        cov_txt, cov_status = "*(not measurable)*", "—"
    else:
        cov_txt = f"{cov:.3f}"
        cov_status = "✅" if 0.88 <= cov <= 0.92 else ("⚠️" if 0.85 <= cov <= 0.95 else "❌")
    lines.append(f"| Conformal 90% coverage (empirical, gold test) | {cov_txt} | 88–92% | {cov_status} |")
    lines.append("| Ultracool subtype within 2 | *(needs SPIFF held-out sample — not yet ingested)* | 80% | — |")
    lines.append("")
    lines.append("> [!NOTE]")
    lines.append("> Conformal coverage is measured on the synthetic gold test split. "
                 "Balanced accuracy and ECE are only meaningful for the synthetic corpus; "
                 "the SPIFF Zenodo / SPLICES ingestion path (`dataset.append_external`) is "
                 "a stub, so no external-validated numbers are claimed here.")
    lines.append("")
    lines.append(f"**spectrum_alone**: balanced accuracy {metrics.get('spectrum_alone_balanced_accuracy', 0.0):.3f}, "
                 f"ECE {metrics.get('spectrum_alone_calibration_error', 0.0):.4f}.\n")

    lines.append("## 2. Five-target side-by-side\n")
    lines.append("| Target | Expected (Section 8) | Model (all_data) | e1 | e2 | Conf | Discovery | Novelty | Artefact |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for t in targets:
        al = t["all_data"]
        sp = t["spectrum_alone"]
        lines.append(
            f"| {t['target_name']} | {EXPECTED.get(t['target_name'], '—')} | {al['top_class']} "
            f"({al['display_confidence']:.0%}) | {al['e1_top_class']} | {al['e2_top_class']} | "
            f"{al['raw_confidence']:.0%} | {al['discovery_class']} | {t['novelty']['percentile']:.0f} | "
            f"{t['artefact']['p_real']:.2f} |"
        )
    lines.append("")

    lines.append("## 3. Layer-2/3 detail (all_data)\n")
    for t in targets:
        al = t["all_data"]
        lines.append(f"### {t['target_name']}\n")
        lines.append(f"- top class: **{al['top_class']}** (unclassified: {al['unclassified']})")
        lines.append(f"- probabilities: {json.dumps(al['probabilities'])}")
        lines.append(f"- conformal set: {al['conformal_set_90']}")
        lines.append(f"- deciding bands: {[b['label'] for b in al['deciding_bands']]}")

    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    report = _assemble_report()
    _update_pack(report)
    REPORT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_md(report)
    print("Wrote:")
    for p in (SOURCES, CASES, REPORT_JSON, REPORT_MD):
        print(f"  {p}  ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()