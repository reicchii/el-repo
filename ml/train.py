"""Train and honestly evaluate the SPHEREx + SPIFF Layer 1-3 ML discovery pipeline."""

import argparse
from datetime import datetime, timezone
import json
import math
import os
import sys

import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from phantom_worlds.contracts import load_spectra_table
from phantom_worlds.ml_pipeline import (
    DEFAULT_PIPELINE_MODEL_VERSION,
    evaluate_cross_extraction_ratio,
    evaluate_fixed_targets,
    evaluate_input_ladder,
    save_pipeline_checkpoint,
    train_from_real_dataset,
)
from phantom_worlds.real_ml_data import (
    DEFAULT_ML_DIR,
    build_balanced_e1_templates,
    load_real_training_dataset,
    resample_spectrum_to_grid,
)

MODEL_VERSION = DEFAULT_PIPELINE_MODEL_VERSION
PIPELINE_VERSION = "phantom-ml-tierb"


def _sanitize_json(obj):
    if isinstance(obj, dict):
        return {str(k): _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json(v) for v in obj]
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.floating, float)):
        val = float(obj)
        return val if math.isfinite(val) else None
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    return obj


def _evaluate_multiclass_subset(pipe, X_sub, y_sub, blends_sub, err_sub=None):
    if len(y_sub) == 0:
        return {"count": 0, "overall_accuracy": 0.0, "e1_only_accuracy": 0.0, "e2_only_accuracy": 0.0, "agreement_rate": 0.0, "per_class": {}}
    preds = [
        pipe.predict_one(
            X_sub[i],
            blend_share=float(blends_sub[i]),
            flux_err=(err_sub[i] if err_sub is not None else None),
        )
        for i in range(len(y_sub))
    ]
    y_list = [str(v) for v in y_sub.tolist()]
    n = len(y_list)
    overall_acc = round(sum(preds[i]["spectrum_alone"]["top_class"] == y_list[i] for i in range(n)) / n, 4)
    e1_acc = round(sum(preds[i]["spectrum_alone"]["template_class"] == y_list[i] for i in range(n)) / n, 4)
    e2_acc = round(sum(preds[i]["spectrum_alone"]["tree_class"] == y_list[i] for i in range(n)) / n, 4)
    agree_rate = round(
        sum(preds[i]["spectrum_alone"]["template_class"] == preds[i]["spectrum_alone"]["tree_class"] for i in range(n)) / n,
        4,
    )
    per_class = {}
    for cls in sorted(set(y_list)):
        idxs = [i for i, yy in enumerate(y_list) if yy == cls]
        m = len(idxs)
        per_class[cls] = {
            "count": m,
            "combined_recall": round(sum(preds[i]["spectrum_alone"]["top_class"] == cls for i in idxs) / m, 4),
            "unclassified_rate": round(sum(preds[i]["spectrum_alone"]["top_class"] == "Unclassified" for i in idxs) / m, 4),
            "e1_recall": round(sum(preds[i]["spectrum_alone"]["template_class"] == cls for i in idxs) / m, 4),
            "e2_recall": round(sum(preds[i]["spectrum_alone"]["tree_class"] == cls for i in idxs) / m, 4),
            "conformal_coverage": round(sum(cls in preds[i]["spectrum_alone"]["conformal_set"] for i in idxs) / m, 4),
        }
    return {
        "count": n,
        "overall_accuracy": overall_acc,
        "e1_only_accuracy": e1_acc,
        "e2_only_accuracy": e2_acc,
        "agreement_rate": agree_rate,
        "per_class": per_class,
    }


def _display_path(path):
    try:
        return os.path.relpath(path, REPO_ROOT).replace("\\", "/")
    except ValueError:
        return os.path.basename(path)


def _format_model_card(report):
    rg = report["release_gates"]
    hi = rg["high_snr_gold"]
    diag = report["heldout_all_classes_diagnostic"]
    lines = [
        "# Phantom Worlds ML Model Card",
        "",
        f"- **Model version:** `{report['model_version']}`",
        f"- **Pipeline version:** `{report['pipeline_version']}`",
        f"- **Data as of:** `{report['data_as_of']}`",
        f"- **Training dataset:** `{report['dataset_path']}` (sha256 `{report['dataset_sha256'][:16]}...`, `{report['total_spectra']}` spectra)",
        f"- **Release gate verdict:** **{rg['release_status']}**",
        f"- **Strict sky-tile disjointness (train / isotonic / conformal / test):** `{report['strict_tile_disjointness']}`",
        "",
        "## 1. Gold-Only Release Gate (`W2 <= 14`)",
        "",
        f"- Gold test samples (`W2 <= 14`): `{hi['count']}` (Silver excluded: `{rg['excluded_silver_count']}`)",
        f"- Minimum per-class recall: `{hi['min_recall']:.4f}` (threshold `>= 0.80`)",
        f"- Expected Calibration Error (ECE): `{hi['ece']:.4f}` (threshold `<= 0.05`)",
        f"- Conformal set coverage: `{hi['conformal_coverage']:.4f}` (threshold `>= 0.88`, `conformal_q={report['conformal_q']:.4f}`)",
        "",
        "| Class / W2 Bin | Count | Recall / Min Recall | ECE | Coverage | Pass |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for bname, bstats in rg["brightness_bins"].items():
        lines.append(
            f"| Bin `{bname}` | {bstats['count']} | {bstats['min_recall']:.4f} | {bstats['ece']:.4f} | {bstats['conformal_coverage']:.4f} | {bstats['passed']} |"
        )
    lines.extend([
        "",
        "## 2. All-6-Class Held-Out Sky-Tile Diagnostic (Gold + Silver)",
        "",
        f"- Held-out spectra: `{diag['count']}` | Combined accuracy: `{diag['overall_accuracy']:.4f}` | E1-only accuracy: `{diag['e1_only_accuracy']:.4f}` | E2-only accuracy: `{diag['e2_only_accuracy']:.4f}` | E1/E2 agreement: `{diag['agreement_rate']:.4f}`",
        "",
        "| Class | Support | Combined Recall | E1 Recall | E2 Recall | Unclassified Rate | Conformal Coverage |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for cls, cstats in diag["per_class"].items():
        lines.append(
            f"| {cls} | {cstats['count']} | {cstats['combined_recall']:.4f} | {cstats['e1_recall']:.4f} | {cstats['e2_recall']:.4f} | {cstats['unclassified_rate']:.4f} | {cstats['conformal_coverage']:.4f} |"
        )
    lines.extend([
        "",
        "## 3. Fixed 5 NASA Benchmark Targets",
        "",
        f"- Real S3 Cube extraction check (`all_passed`): `{report['fixed_targets_cube']['all_passed']}`",
        f"- Clean reference 102-band check (`all_passed`): `{report['fixed_targets_reference']['all_passed']}`",
        "",
        "| Target | S3 Cube Pred | S3 Molecule | Ref 102 Pred | Ref Molecule |",
        "|---|---|---|---|---|",
    ])
    for slug, cinfo in report["fixed_targets_cube"]["targets"].items():
        rinfo = report["fixed_targets_reference"]["targets"].get(slug, {})
        lines.append(
            f"| `{slug}` | {cinfo['top_class']} | {cinfo['molecule_status']} | {rinfo.get('top_class', '-')} | {rinfo.get('molecule_status', '-')} |"
        )
    ucd_sub = report.get("ucd_subtype_evaluation") or {}
    if ucd_sub:
        lines.extend([
            "",
            "## 4. Ultracool Dwarf Level-2 Subtype & Input Ladder (Tier B)",
            "",
            f"- Held-out SPIFF UCD subtype count: `{ucd_sub.get('count', 0)}` | Within 2 subtypes: `{ucd_sub.get('within_2_subtypes_frac', 0.0):.4f}` (gate `>= 0.80`) | MAD: `{ucd_sub.get('mad_subtypes')}` | Pass: `{ucd_sub.get('passed')}`",
        ])
    cross = report.get("cross_extraction_ratio")
    if cross:
        lines.append(
            f"- Cross-extraction ratio (`our S3 cube / SPIFF ref`, n=`{cross.get('matched_count', 0)}`): max abs band median deviation `{cross.get('max_abs_deviation')}` (gate `<= 0.10`) | Pass: `{cross.get('passed')}`"
        )
    ladder = report.get("input_ladder") or {}
    if ladder:
        lines.extend([
            "",
            "| Input Ladder Rung | Features | All-Class Acc | Gold Test Acc |",
            "|---|---:|---:|---:|",
        ])
        for rung_name, rstats in ladder.items():
            lines.append(
                f"| `{rung_name}` | {rstats.get('n_features', 0)} | {rstats.get('test_all_accuracy', 0.0):.4f} | {rstats.get('test_gold_accuracy', 0.0):.4f} |"
            )
    lines.extend([
        "",
        "## 5. Known Limitations & Honest Framing",
        "",
        "- Model estimates are probabilistic (`estimate`) and output `Unclassified` capped at confidence `<= 0.50` whenever Expert 1 templates and Expert 2 gradient-boosted trees disagree.",
        "- S3 All-Sky Cubes use HiPS Order 5 (`~13.98 arcsec/px`), which is ~2.25x coarser than native SPHEREx Level-2 (`~6.2 arcsec/px`) and increases blending for faint or crowded sources (e.g., WISE 0855 at short wavelengths, saturating bright red giants/dwarfs in D1-D4).",
        "- Classes `Star`, `Galaxy`, and `Evolved giant star` rely on `silver` cross-matched Gaia/SIMBAD/ALLWISE labels weighted `0.5x` during fit and excluded from Gold-only release gating.",
    ])
    return "\n".join(lines) + "\n"


def run_training(
    dataset_path=os.path.join(DEFAULT_ML_DIR, "real_training_dataset.npz"),
    output_dir=DEFAULT_ML_DIR,
    max_per_class=14,
    seed=42,
    log_file=None,
):
    """Train on real_training_dataset.npz and write honest evaluation_report.json and model_card.md."""
    def _log(msg):
        line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}] {msg}"
        print(line, flush=True)
        if log_file:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
            with open(log_file, "a", encoding="utf-8", newline="\n") as lf:
                lf.write(line + "\n")

    _log(f"Loading real dataset: {dataset_path}")
    dataset = load_real_training_dataset(dataset_path)
    wl = np.asarray(dataset["wavelength_um"], dtype=np.float64)
    bw = np.asarray(dataset["bandwidth_um"], dtype=np.float64)
    X = np.asarray(dataset["X_flux_uJy"], dtype=np.float64)
    X_err = np.asarray(dataset["X_err_uJy"], dtype=np.float64) if "X_err_uJy" in dataset else None
    y = np.asarray(dataset["y_class"])
    grades = np.asarray(dataset["label_grades"])
    w2 = np.asarray(dataset["w2_mag_est"], dtype=np.float64)
    blends = np.asarray(dataset["blend_shares"], dtype=np.float64)
    _log(f"Dataset loaded: N={len(y)}, bands={len(wl)}, finite_frac={float(np.mean(np.isfinite(X))):.4f}")

    fit_res = train_from_real_dataset(dataset, build_balanced_e1_templates, max_per_class=max_per_class, random_state=seed)
    pipe = fit_res["pipeline"]
    tmpl_counts = {cls: len(vs) for cls, vs in fit_res["e1_templates"].items()}
    _log(
        f"Fit complete: strict_tile_disjointness={fit_res['strict_tile_disjointness']} | "
        f"train={len(fit_res['tr_rel'])}, iso={pipe.isotonic_size_}, conf={pipe.calibration_size_}, "
        f"conformal_q={pipe.conformal_q_:.4f}"
    )
    _log(f"E1 template counts per class (max={max_per_class}): {json.dumps(tmpl_counts)}")

    te_gold_idx = fit_res["test_gold_idx"]
    te_all_idx = fit_res["test_all_idx"]
    release_gates = pipe.evaluate_release_gates(
        X[te_gold_idx],
        y[te_gold_idx],
        w2_mags=w2[te_gold_idx],
        label_grades=grades[te_gold_idx],
        blend_shares=blends[te_gold_idx],
        X_err=(X_err[te_gold_idx] if X_err is not None else None),
    )
    _log(
        f"Gold release gate status={release_gates['release_status']} | "
        f"W2<=14 count={release_gates['high_snr_gold']['count']} "
        f"min_recall={release_gates['high_snr_gold']['min_recall']:.4f} "
        f"ece={release_gates['high_snr_gold']['ece']:.4f} "
        f"coverage={release_gates['high_snr_gold']['conformal_coverage']:.4f}"
    )

    all_diag = _evaluate_multiclass_subset(
        pipe,
        X[te_all_idx],
        y[te_all_idx],
        blends[te_all_idx],
        err_sub=(X_err[te_all_idx] if X_err is not None else None),
    )
    _log(
        f"All-6-class held-out tiles ({all_diag['count']} spectra): "
        f"acc={all_diag['overall_accuracy']:.4f} e1={all_diag['e1_only_accuracy']:.4f} "
        f"e2={all_diag['e2_only_accuracy']:.4f} agree={all_diag['agreement_rate']:.4f}"
    )
    for cls, cstats in all_diag["per_class"].items():
        _log(
            f"  Class '{cls}' (n={cstats['count']}): comb_rec={cstats['combined_recall']:.4f}, "
            f"e1={cstats['e1_recall']:.4f}, e2={cstats['e2_recall']:.4f}, unclass={cstats['unclassified_rate']:.4f}"
        )

    cube_bench = {
        str(slug): dataset["benchmark_flux_uJy"][i]
        for i, slug in enumerate(dataset["benchmark_slugs"].tolist())
    }
    cube_errs = (
        {
            str(slug): dataset["benchmark_err_uJy"][i]
            for i, slug in enumerate(dataset["benchmark_slugs"].tolist())
        }
        if "benchmark_err_uJy" in dataset
        else None
    )
    for slug in ("Barnards_Star", "Eps_Indi_B", "WISE_0855", "RW_Aurigae", "R_Draconis"):
        cube_bench.setdefault(slug, np.full(len(wl), np.nan, dtype=np.float64))
    fixed_cube = evaluate_fixed_targets(wl, bw, cube_bench, pipe, errs_by_slug=cube_errs)

    ref_tbl = load_spectra_table()
    ref_wl = np.asarray(ref_tbl["wavelength_um"], dtype=np.float64)
    ref_bench = {}
    for slug in fixed_cube["targets"]:
        raw_fl = np.array([float(r[f"{slug}_uJy"]) for r in ref_tbl["rows"]], dtype=np.float64)
        ref_bench[slug] = resample_spectrum_to_grid(ref_wl, raw_fl, wl)
    fixed_ref = evaluate_fixed_targets(wl, bw, ref_bench, pipe)
    _log(
        f"Fixed 5 benchmarks: cube_all_passed={fixed_cube['all_passed']}, "
        f"ref_all_passed={fixed_ref['all_passed']}"
    )

    ucd_subtype_eval = (
        pipe.evaluate_ucd_subtype_accuracy(X[te_all_idx], y[te_all_idx], dataset["subclass"][te_all_idx])
        if "subclass" in dataset
        else {"count": 0, "mad_subtypes": None, "mae_subtypes": None, "within_2_subtypes_frac": 0.0, "passed": False}
    )
    _log(
        f"UCD Level-2 Subtypes (n={ucd_subtype_eval['count']}): within_2={ucd_subtype_eval['within_2_subtypes_frac']:.4f}, "
        f"mad={ucd_subtype_eval['mad_subtypes']}, passed={ucd_subtype_eval['passed']}"
    )

    input_ladder = evaluate_input_ladder(dataset, fit_res, random_state=seed)
    for rname, rstats in input_ladder.items():
        _log(
            f"Input ladder {rname}: n_feat={rstats['n_features']} all_acc={rstats['test_all_accuracy']:.4f} "
            f"gold_acc={rstats['test_gold_accuracy']:.4f}"
        )

    cross_extract_eval = None
    if "cross_extract_ours_uJy" in dataset and "cross_extract_ref_uJy" in dataset and len(dataset["cross_extract_ours_uJy"]) > 0:
        cross_extract_eval = evaluate_cross_extraction_ratio(
            dataset["cross_extract_ours_uJy"], dataset["cross_extract_ref_uJy"]
        )
        cross_extract_eval["matched_count"] = int(len(dataset["cross_extract_ours_uJy"]))
        cross_extract_eval["matched_slugs"] = [str(s) for s in dataset.get("cross_extract_slugs", []).tolist()]
        _log(
            f"Cross-extraction S3 vs SPIFF (n={cross_extract_eval['matched_count']}): "
            f"max_dev={cross_extract_eval['max_abs_deviation']}, passed={cross_extract_eval['passed']}"
        )

    disp_dataset = _display_path(dataset_path)
    os.makedirs(output_dir, exist_ok=True)
    ckpt_res = save_pipeline_checkpoint(
        pipe,
        fit_res["e1_templates"],
        dataset_path,
        output_dir,
        model_version=MODEL_VERSION,
        max_per_class=max_per_class,
        random_state=seed,
    )
    ckpt_meta = ckpt_res["meta"]
    _log(
        f"Exported model checkpoint: {ckpt_res['checkpoint_path']} "
        f"({ckpt_meta['checkpoint_bytes']} B, sha256={ckpt_meta['checkpoint_sha256'][:16]}...)"
    )
    report = _sanitize_json(
        {
            "model_version": MODEL_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "data_as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_files": [
                disp_dataset,
                "ml/dataset_manifest.json",
                "phantom_worlds/ml_pipeline.py",
                "phantom_worlds/real_ml_data.py",
            ],
            "dataset_path": disp_dataset,
            "dataset_sha256": ckpt_meta["dataset_sha256"],
            "checkpoint_file": _display_path(ckpt_res["checkpoint_path"]),
            "checkpoint_sha256": ckpt_meta["checkpoint_sha256"],
            "total_spectra": int(len(y)),
            "strict_tile_disjointness": fit_res["strict_tile_disjointness"],
            "conformal_q": round(float(pipe.conformal_q_), 4),
            "temperature_inv": round(float(pipe.temperature_inv_), 4),
            "silver_weight_applied": float(pipe.silver_weight_applied_),
            "split_sizes": {
                "train_core": int(len(fit_res["tr_rel"])),
                "isotonic": int(pipe.isotonic_size_),
                "conformal": int(pipe.calibration_size_),
                "test_gold": int(len(te_gold_idx)),
                "test_all_classes": int(len(te_all_idx)),
            },
            "e1_templates_per_class": tmpl_counts,
            "release_gates": release_gates,
            "heldout_all_classes_diagnostic": all_diag,
            "ucd_subtype_evaluation": ucd_subtype_eval,
            "input_ladder": input_ladder,
            "cross_extraction_ratio": cross_extract_eval,
            "fixed_targets_cube": fixed_cube,
            "fixed_targets_reference": fixed_ref,
        }
    )

    report_path = os.path.join(output_dir, "evaluation_report.json")
    card_path = os.path.join(output_dir, "model_card.md")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, allow_nan=False)
    with open(card_path, "w", encoding="utf-8") as f:
        f.write(_format_model_card(report))
    _log(f"Wrote honest report & model card: {report_path}, {card_path}")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Train and evaluate the SPHEREx + SPIFF discovery pipeline.")
    parser.add_argument("--dataset", default=os.path.join(DEFAULT_ML_DIR, "real_training_dataset.npz"))
    parser.add_argument("--output-dir", default=DEFAULT_ML_DIR)
    parser.add_argument("--max-per-class", type=int, default=14)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--log-file", default=None)
    args = parser.parse_args(argv)
    report = run_training(
        dataset_path=args.dataset,
        output_dir=args.output_dir,
        max_per_class=args.max_per_class,
        seed=args.seed,
        log_file=args.log_file,
    )
    print(json.dumps({"release_status": report["release_gates"]["release_status"], "all_class_acc": report["heldout_all_classes_diagnostic"]["overall_accuracy"]}, indent=2))


if __name__ == "__main__":
    main()
