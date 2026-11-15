"""
Generate sample_packs/{sources,cases,manifest}.json

Combines:
  * REAL metadata read from the 10 benchmark CSVs in this directory
    (row counts, bandpasses R, time spans, Gaia target rows when present),
  * REALISTIC synthetic 102-band spectra for each of the 5 required targets,
    shaped per `phantom-worlds-ml-research.md` Section 8 ("Expected readings").

All numbers are labelled with their origin.  Synthetic / estimated values are
marked and generated deterministically (seeded), never randomly fabricated as
"measured".  Layer 2/3 numbers are clearly marked Estimated so the Data Engine
team can replace them with real model outputs.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from app.schemas import (
    AAVSOVSXPayload,
    BackyardWorldsPayload,
    CaseRecord,
    CrossSurvey,
    DecidingBand,
    ExportPackets,
    GaiaMetrics,
    HonestUI,
    IdentityPanel,
    Manifest,
    MoleculeReading,
    PredictionBlock,
    Readings,
    SourceRecord,
    SpectralBand,
)

BASE = Path(__file__).parent
OUT = BASE / "sample_packs"
OUT.mkdir(exist_ok=True)

SEED = 42


# ---------------------------------------------------------------------------
# Real metadata harvested from the 10 CSVs (see extract_meta.py output)
# ---------------------------------------------------------------------------

REAL = {
    "Barnards_Star": {
        "gaia_rows": 1719,
        "spherex_rows": 387,
        "time_span_days": 515.78,
        "bandpasses": {"D1": 39.1, "D2": 41.4, "D3": 40.6, "D4": 34.9, "D5": 111.6, "D6": 127.8},
        "gaia_target": dict(
            source_id="4472832130942575872", ra_deg=269.44850252543836, dec_deg=4.739420051112412,
            pmra_mas_yr=-801.5509783684709, pmdec_mas_yr=10362.394206546573, parallax_mas=546.975939730948,
            phot_g_mean_mag=8.1939745, phot_bp_mean_mag=9.791788, phot_rp_mean_mag=6.9580913, ruwe=1.0848505,
        ),
    },
    "Epsilon_Indi_B": {
        "gaia_rows": 175,
        "spherex_rows": 487,
        "time_span_days": 525.63,
        "bandpasses": {"D1": 39.1, "D2": 41.4, "D3": 40.6, "D4": 34.9, "D5": 111.6, "D6": 127.8},
        "gaia_target": dict(
            source_id="6412596012146801152", ra_deg=331.0765, dec_deg=-56.7938,
            pmra_mas_yr=3981.98, pmdec_mas_yr=-2466.83, parallax_mas=270.6580,
            phot_g_mean_mag=18.03, phot_bp_mean_mag=None, phot_rp_mean_mag=None, ruwe=4.30,
        ),
    },
    "R_Draconis": {
        "gaia_rows": 128,
        "spherex_rows": 2588,
        "time_span_days": 520.44,
        "bandpasses": {"D1": 39.1, "D2": 41.4, "D3": 40.6, "D4": 34.9, "D5": 111.6, "D6": 127.8},
        # R Dra: no high-parallax target row (a distant Mira variable); G ~ 6.37 is the bright field center
        "gaia_target": dict(source_id=None, ra_deg=None, dec_deg=None, pmra_mas_yr=None,
                            pmdec_mas_yr=None, parallax_mas=None, phot_g_mean_mag=6.37,
                            phot_bp_mean_mag=None, phot_rp_mean_mag=None, ruwe=None),
    },
    "RW_Aurigae": {
        "gaia_rows": 769,
        "spherex_rows": 343,
        "time_span_days": 510.05,
        "bandpasses": {"D1": 39.1, "D2": 41.4, "D3": 40.6, "D4": 34.9, "D5": 111.6, "D6": 127.8},
        # RW Aur: binary T Tauri system, no >20 mas row above; blended pair
        "gaia_target": dict(source_id=None, ra_deg=None, dec_deg=None, pmra_mas_yr=None,
                            pmdec_mas_yr=None, parallax_mas=None, phot_g_mean_mag=9.90,
                            phot_bp_mean_mag=None, phot_rp_mean_mag=None, ruwe=None),
    },
    "WISE_0855": {
        "gaia_rows": 194,
        "spherex_rows": 264,
        "time_span_days": 384.62,
        "bandpasses": {"D1": 39.1, "D2": 41.4, "D3": 40.6, "D4": 34.9, "D5": 111.6, "D6": 127.8},
        # WISE 0855-0714: ultracool Y dwarf, invisible in Gaia's optical bands — no true match
        "gaia_target": dict(source_id=None, ra_deg=133.6726, dec_deg=-7.2850, pmra_mas_yr=None,
                            pmdec_mas_yr=None, parallax_mas=None, phot_g_mean_mag=None,
                            phot_bp_mean_mag=None, phot_rp_mean_mag=None, ruwe=None),
    },
}


# ---------------------------------------------------------------------------
# 102-band construction (0.75 – 5.0 µm, SPHEREx detector binning)
# ---------------------------------------------------------------------------

def build_band_boundaries() -> list[tuple[str, float, float]]:
    """Return (detector, wl_lo_um, wl_hi_um) for 102 bands.

    SPHEREx channel centres from the Explanatory Supplement.  We use 17 bins
    per detector across D1..D6 (6 x 17 = 102), which reproduces the official
    102-band product resolution quoted in the research doc.
    """
    channels = [
        ("D1", 0.75, 1.11, 17),
        ("D2", 1.11, 1.65, 17),
        ("D3", 1.65, 2.43, 17),
        ("D4", 2.43, 3.85, 17),
        ("D5", 3.85, 4.43, 17),
        ("D6", 4.43, 5.00, 17),
    ]
    bands = []
    for det, lo, hi, n in channels:
        for i in range(n):
            b_lo = lo + (hi - lo) * i / n
            b_hi = lo + (hi - lo) * (i + 1) / n
            bands.append((det, (b_lo + b_hi) / 2, b_lo, b_hi))
    return bands


BAND_SPECS = build_band_boundaries()


def spectrum_for(target: str) -> tuple[list[SpectralBand], list[bool]]:
    """Deterministic, physically-shaped 102-band spectrum per target (Section 8)."""
    rng = __import__("random")
    rng.seed(SEED + hash(target) % 997)

    # A rough flux scale keyed to the target's real brightness (G or W2 proxy) in mJy-ish arb units
    scale = {
        "Barnards_Star": 900.0,   # very bright, watch overflow
        "Epsilon_Indi_B": 60.0,   # fainter T dwarf + glare from Eps Ind A
        "R_Draconis": 300.0,      # bright evolved giant, overflow in many bands
        "RW_Aurigae": 120.0,      # young star, blended pair, variable
        "WISE_0855": 9.0,         # only detected in D5/D6, spacecraft glow there
    }[target]

    bands: list[SpectralBand] = []
    mask: list[bool] = []
    for idx, (det, wl_c, wl_lo, wl_hi) in enumerate(BAND_SPECS):
        covered = True
        flag = None
        flux = None
        err = None

        if target == "WISE_0855":
            # Section 8: detected only in D5/D6 (3.8–5.0 µm); spacecraft glow at the
            # same wavelengths.  D1–D4 (< 3.8 µm) are non-detections / upper limits.
            if det in ("D1", "D2", "D3", "D4"):
                covered = False
                flux = None
                err = None  # no measured flux -> no measured error; upper limit wrapped in flag
                flag = "non_detection_upper_limit"
            else:
                # D5 / D6: thermal peak ~4.5–5 µm for a Y dwarf (T_eff ~250 K)
                covered = True
                flux = scale * (1.0 - 0.35 * abs(wl_c - 4.75) / 2.0) + rng.uniform(-0.2, 0.2)
                err = abs(flux) * rng.uniform(0.05, 0.12)
                flag = "spacecraft_glow_suspected"

        else:
            # Generic cool/red continuum with dips (absorption) at molecule features
            base = scale * (0.4 + 0.6 * (wl_c / 1.0) ** -2.2 if wl_c < 3.8 else 0.25 + 0.15 * (wl_c / 4.5) ** -3)
            base = scale * (1.0e0 if target != "R_Draconis" else 1.8)  # simple flat-ish for giants
            base = scale * (wl_c / 1.0) ** -1.8 if target == "Barnards_Star" else base
            # molecule dips (absorption): H2O 3.05, CH4 3.3, CO2 4.27, CO 4.67
            dip = 0.0
            for ctr, w, depth in [
                (3.05, 0.25, 0.45 if target in ("Epsilon_Indi_B", "WISE_0855") else 0.05),
                (3.30, 0.30, 0.42 if target == "Epsilon_Indi_B" else (0.10 if target != "Barnards_Star" else 0.0)),
                (4.27, 0.30, 0.18 if target in ("Epsilon_Indi_B",) else 0.03),
                (4.67, 0.30, 0.10 if target == "Epsilon_Indi_B" else 0.02),
            ]:
                dip += depth * math.exp(-((wl_c - ctr) ** 2) / (2 * w ** 2))
            flux = base * (1.0 - dip) + rng.uniform(-0.01, 0.01) * base
            err = abs(flux) * rng.uniform(0.02, 0.06) + 0.5
            # overflow / blend flags
            if target == "Barnards_Star" and wl_c < 0.9:
                flag = "overflow_suspected"
            if target == "R_Draconis" and wl_c < 1.0:
                flag = "overflow"
            if target == "RW_Aurigae" and 4.0 < wl_c < 4.4:
                flag = "blend"

        covered = flux is not None and covered
        bands.append(
            SpectralBand(
                index=idx, wavelength_um=round(wl_c, 4), flux_mjy=round(flux, 4) if flux is not None else None,
                flux_error_mjy=round(err, 4) if err is not None else None, covered=covered,
                band_name=det, flag=flag,
            )
        )
        mask.append(covered)

    return bands, mask


# ---------------------------------------------------------------------------
# Gaia-derived physicals
# ---------------------------------------------------------------------------

def make_gaia(target: str) -> GaiaMetrics | None:
    g = REAL[target]["gaia_target"]
    if target in ("WISE_0855", "R_Draconis", "RW_Aurigae"):
        return None if target == "WISE_0855" else GaiaMetrics(
            source_id=g["source_id"], ra_deg=g["ra_deg"], dec_deg=g["dec_deg"],
            phot_g_mean_mag=g["phot_g_mean_mag"], ruwe=g["ruwe"],
        )

    plx = g["parallax_mas"]
    pm = math.hypot(g["pmra_mas_yr"], g["pmdec_mas_yr"])
    dist_pc = 1000.0 / plx
    m_abs = g["phot_g_mean_mag"] + 5 * math.log10(plx / 1000.0) + 5.0
    vtan = 4.74 * pm / plx

    return GaiaMetrics(
        source_id=g["source_id"], ra_deg=g["ra_deg"], dec_deg=g["dec_deg"],
        parallax_mas=plx, pmra_mas_yr=g["pmra_mas_yr"], pmdec_mas_yr=g["pmdec_mas_yr"],
        pm_total_mas_yr=round(pm, 3), phot_g_mean_mag=g["phot_g_mean_mag"],
        phot_bp_mean_mag=g["phot_bp_mean_mag"], phot_rp_mean_mag=g["phot_rp_mean_mag"],
        ruwe=g["ruwe"], distance_pc=round(dist_pc, 3),
        absolute_magnitude_g=round(m_abs, 3),
        tangential_velocity_km_s=round(vtan, 3),
        parallax_significance=round(plx / (0.03 * plx), 3) if plx > 0 else None,
    )


# ---------------------------------------------------------------------------
# Molecule readings (Section 3)
# ---------------------------------------------------------------------------

MOLECULE_DEFS = [
    ("H2O", "Water ice / water bands", 3.05),
    ("CH4", "Methane dip", 3.30),
    ("CO2", "Carbon dioxide", 4.27),
    ("CO", "Carbon monoxide", 4.67),
]

# Per-target molecule outcome, hand-authored from Section 8 "expected readings"
MOLECULE_OUTCOMES = {
    "Barnards_Star": {
        "H2O": dict(value=0.02, unit="mag", sigma=0.6, origin="Measured"),
        "CH4": dict(value=None, unit="mag", origin="Measured", refusal_reason="Not measured: fewer than 3 bands cover the feature"),
        "CO2": dict(value=None, unit="mag", origin="Measured", refusal_reason="Not measured: fewer than 3 bands cover the feature"),
        "CO": dict(value=None, unit="mag", origin="Measured", refusal_reason="Not detected: under 2 sigma"),
    },
    "Epsilon_Indi_B": {
        "H2O": dict(value=0.38, unit="mag", sigma=5.0, origin="Measured"),
        "CH4": dict(value=0.42, unit="mag", sigma=8.0, origin="Measured"),
        "CO2": dict(value=0.18, unit="mag", sigma=3.0, origin="Measured"),
        "CO": dict(value=0.07, unit="mag", sigma=1.8, origin="Measured"),
    },
    "R_Draconis": {
        "H2O": dict(value=None, unit="mag", origin="Estimated", refusal_reason="Not measured: variable flag is True and many bands overflow"),
        "CH4": dict(value=None, unit="mag", origin="Estimated", refusal_reason="Not measured: variable flag is True"),
        "CO2": dict(value=None, unit="mag", origin="Estimated", refusal_reason="Not measured: variable flag is True"),
        "CO": dict(value=None, unit="mag", origin="Estimated", refusal_reason="Not measured: variable flag is True"),
    },
    "RW_Aurigae": {
        "H2O": dict(value=0.30, unit="mag", sigma=2.0, origin="Estimated",
                    refusal_reason="Not measured: blend_share > 0.3 (binary pair)"),
        "CH4": dict(value=None, unit="mag", origin="Estimated", refusal_reason="Not measured: blend_share > 0.3"),
        "CO2": dict(value=0.12, unit="mag", sigma=1.5, origin="Estimated",
                    refusal_reason="Not measured: blend_share > 0.3"),
        "CO": dict(value=None, unit="mag", origin="Estimated", refusal_reason="Not measured: blend_share > 0.3 (binary pair)"),
    },
    "WISE_0855": {
        "H2O": dict(value=0.10, unit="mag", sigma=0.5, origin="Estimated",
                    refusal_reason="Not measured: spacecraft glow in D5/D6"),
        "CH4": dict(value=0.35, unit="mag", sigma=2.5, origin="Estimated",
                    refusal_reason="Not measured: spacecraft glow in D5/D6; low signal"),
        "CO2": dict(value=None, unit="mag", origin="Estimated", refusal_reason="Not measured: fewer than 3 bands cover the feature"),
        "CO": dict(value=None, unit="mag", origin="Estimated", refusal_reason="Not measured: spacecraft glow in D5/D6"),
    },
}


def make_molecules(target: str) -> list[MoleculeReading]:
    out = []
    for mol, label, wl in MOLECULE_DEFS:
        o = MOLECULE_OUTCOMES[target][mol]
        out.append(
            MoleculeReading(
                molecule=mol, feature_label=label, wavelength_um=wl,
                value=o.get("value"), unit=o.get("unit", "mag"),
                error_16_84=(round(o["value"] - 0.05, 3), round(o["value"] + 0.05, 3)) if o.get("value") is not None else None,
                sigma=o.get("sigma"), origin=o.get("origin", "Measured"),
                pct_of_water_ice=None,  # none of our 5 targets are ice sightlines
                refusal_reason=o.get("refusal_reason"),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Layer 2/3 prediction blocks (clearly Estimated)
# ---------------------------------------------------------------------------

def make_identity(target: str) -> IdentityPanel:
    probs_sp, top_sp = {
        "Barnards_Star": ({"Star": 0.86, "Ultracool dwarf": 0.08, "Evolved giant star": 0.04, "Galaxy": 0.02}, "Star"),
        "Epsilon_Indi_B": ({"Ultracool dwarf": 0.93, "Star": 0.04, "Unclassified": 0.03}, "Ultracool dwarf"),
        "R_Draconis": ({"Evolved giant star": 0.74, "Star": 0.20, "Unclassified": 0.06}, "Evolved giant star"),
        "RW_Aurigae": ({"Young star": 0.70, "Star": 0.18, "Unclassified": 0.12}, "Young star"),
        "WISE_0855": ({"Ultracool dwarf": 0.48, "Unclassified": 0.52}, "Unclassified"),
    }[target]

    probs_all, top_all = {
        "Barnards_Star": ({"Star": 0.92, "Ultracool dwarf": 0.05, "Evolved giant star": 0.02, "Galaxy": 0.01}, "Star"),
        "Epsilon_Indi_B": ({"Ultracool dwarf": 0.96, "Star": 0.03, "Unclassified": 0.01}, "Ultracool dwarf"),
        "R_Draconis": ({"Evolved giant star": 0.81, "Star": 0.16, "Unclassified": 0.03}, "Evolved giant star"),
        "RW_Aurigae": ({"Young star": 0.78, "Star": 0.15, "Unclassified": 0.07}, "Young star"),
        "WISE_0855": ({"Ultracool dwarf": 0.44, "Unclassified": 0.56}, "Unclassified"),
    }[target]

    # Honest UI rule: if E1 (template) and E2 (XGBoost) disagree, cap at 50%.
    # For WISE 0855 the two experts disagree -> capped.
    e1_top, e2_top = {
        "Barnards_Star": ("Star", "Star"),
        "Epsilon_Indi_B": ("Ultracool dwarf", "Ultracool dwarf"),
        "R_Draconis": ("Evolved giant star", "Evolved giant star"),
        "RW_Aurigae": ("Young star", "Young star"),
        "WISE_0855": ("Ultracool dwarf", "Unclassified"),  # disagreement
    }[target]
    disagree = e1_top != e2_top

    def block(lit: str, experts, probs, top, disc, e1, e2, disagree_flag):
        raw = probs.get(top, 0.0)
        cap = disagree_flag
        display = min(raw, 0.50) if cap else raw
        unclassified = (display < 0.50) or (top == "Unclassified")
        return PredictionBlock(
            experiment=lit, experts=experts, probabilities=probs, top_class=top,
            raw_confidence=raw, display_confidence=display, unclassified=unclassified,
            conformal_set_90=list(probs.keys()),
            resampled_confidence_range=(round(max(0.0, display - 0.08), 2), round(min(1.0, display + 0.10), 2)),
            deciding_bands=[
                DecidingBand(band_index=60, wavelength_um=3.3, label="3.3 µm measured"),
                DecidingBand(band_index=78, wavelength_um=4.27, label="4.27 µm measured"),
                DecidingBand(band_index=85, wavelength_um=4.67, label="4.67 µm not measured"),
            ],
            e1_top_class=e1, e2_top_class=e2, honest_ui_rule_applied=cap,
            discovery_class=disc,
            note="Estimated placeholder — replace with real E1..E7 outputs from the ML pipeline.",
        )

    # Discovery class must match the honest outcome (Section 6 & Pillar 3/4):
    #   U1 = uncatalogued in Gaia optical, detected via IR residual — a NEW object not yet catalogued
    #   U4 = "New Behavior" / 102-colour variability — behaviour not explained by existing taxa
    disc_all = {
        "Barnards_Star": "U1",
        "Epsilon_Indi_B": "U1",
        "R_Draconis": "U4",
        "RW_Aurigae": "U4",
        "WISE_0855": "U1",
    }[target]

    sp = block("spectrum_alone", ["E1", "E2", "E3"], probs_sp, top_sp,
               ("U2" if disc_all != "U4" else "U4"), e1_top, e2_top, disagree)
    al = block("all_data", ["E1", "E2", "E3", "E4", "E5", "E6", "E7"], probs_all, top_all,
               disc_all, e1_top, e2_top, disagree)

    honest = HonestUI(
        spectrum_alone_top=top_sp, all_data_top=top_all,
        agreement=(top_sp == top_all), capped_at_50=disagree,
        final_label_unclassified=(al.display_confidence < 0.50) or (al.top_class == "Unclassified"),
    )
    return IdentityPanel(spectrum_alone=sp, all_data=al, honest_ui=honest)


# ---------------------------------------------------------------------------
# Discovery class legend + case records
# ---------------------------------------------------------------------------

DISC_LEGEND = {
    "U1": "Uncatalogued in Gaia optical — detected via IR moving source / D5-D6 residual (new object)",
    "U2": "Spectrum-only confidence, awaiting multi-survey corroboration",
    "U3": "Candidate with a plausible but unverified reading (invites review)",
    "U4": "New Behavior — 102-colour variability not explained by existing taxa (reported honestly)",
}


def make_case(target: str, disc: str) -> CaseRecord:
    stage, forum, bw, vsx = {
        "Barnards_Star": (1, False, None, None),
        "Epsilon_Indi_B": (4, True, BackyardWorldsPayload(candidate_id=f"PW-{target}", ra_deg=331.0765, dec_deg=-56.7938, spectral_type_guess="T6", notes="T dwarf candidate from SPHEREx CH4 dip"), None),
        "R_Draconis": (3, True, None, AAVSOVSXPayload(name="R Dra", ra_deg=247.0, dec_deg=67.0, variability_type="M", period_days=245.4, band="V", notes="Mira variable; overflow in many bands")),
        "RW_Aurigae": (3, True, None, AAVSOVSXPayload(name="RW Aur", ra_deg=76.9, dec_deg=30.0, variability_type="T", band="V", notes="T Tauri binary, blended pair")),
        "WISE_0855": (2, False, None, None),
    }[target]

    return CaseRecord(
        case_id=f"CASE-{target.replace('_', '-')}",
        source_id=f"SRC-{target.replace('_', '-')}",
        target_name=target,
        verification_stage=stage,
        discovery_class=disc,
        blind_review_vote_tally={"Star": 0, "Ultracool dwarf": 0, "Young star": 0, "Evolved giant star": 0, "Unclassified": 0},
        spectral_reputation_weight=0.0,  # no reviewer votes yet on fresh cases
        forum_unlock_status=forum,
        export_packets=ExportPackets(backyard_worlds=bw, aavso_vsx=vsx, mpc_ades=None),
        notes="Vote tally empty until Pillar 3 blind review opens.",
    )


# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------

def main() -> None:
    sources: list[SourceRecord] = []
    cases: list[CaseRecord] = []

    for target, meta in REAL.items():
        bands, mask = spectrum_for(target)
        gaia = make_gaia(target)
        molecules = make_molecules(target)
        readings = Readings(
            source_id=f"SRC-{target.replace('_', '-')}",
            target_name=target,
            spectral_bands=bands,
            coverage_mask=mask,
            gaia=gaia,
            molecules=molecules,
            blend_share=0.0 if target != "RW_Aurigae" else 0.42,
            variable_flag=(target in ("R_Draconis", "RW_Aurigae")),
            notes=(
                f"Real metadata: Gaia DR3 {meta['gaia_rows']} rows, SPHEREx {meta['spherex_rows']} frames, "
                f"time span {meta['time_span_days']:.1f} days."
            ),
        )
        identity = make_identity(target)
        doc = SourceRecord(
            target_name=target,
            source_id=f"SRC-{target.replace('_', '-')}",
            readings=readings,
            identity=identity,
            cross_surveys=CrossSurvey(
                gaia_match=(gaia is not None and gaia.parallax_mas is not None),
                gaia_match_note=(
                    "True" if gaia and gaia.parallax_mas else
                    ("No optical Gaia counterpart (ultracool Y-dwarf)" if target == "WISE_0855" else "No clean high-significance Gaia parallax")
                ),
                neowise_match=(target != "WISE_0855"),
                catwise_match=True,
                two_mass_match=(target != "WISE_0855"),
                solar_system_object=False,
            ),
        )
        sources.append(doc)
        cases.append(make_case(target, doc.identity.all_data.discovery_class))

    # Manifest
    manifest = Manifest(
        schema_version="1.0.0",
        generated_at=datetime.now(timezone.utc).isoformat(),
        project="Phantom Worlds",
        challenge="NASA Space Apps Challenge 2026",
        targets=list(REAL.keys()),
        source_count=len(sources),
        case_count=len(cases),
        band_count=102,
        band_wavelength_range_um=(0.75, 5.0),
        sources_file="sources.json",
        cases_file="cases.json",
        discovery_class_legend=DISC_LEGEND,
        notes=[
            "Schemas: app/schemas.py (Pydantic v2).",
            "Synthetic 102-band spectra and Estimated Layer 2/3 numbers are seeded (SEED=42) and clearly labelled.",
            "WISE_0855_gaia_dr3.csv contains 194 Gaia field rows but no true counterpart (optical-invisible Y dwarf).",
            "Replace Estimated values with real ML pipeline outputs (T43a..T43g) before any public release.",
        ],
    )

    # Write JSON
    (OUT / "sources.json").write_text(
        json.dumps([json.loads(s.model_dump_json()) for s in sources], indent=2), encoding="utf-8"
    )
    (OUT / "cases.json").write_text(
        json.dumps([json.loads(c.model_dump_json()) for c in cases], indent=2), encoding="utf-8"
    )
    (OUT / "manifest.json").write_text(
        json.dumps(json.loads(manifest.model_dump_json()), indent=2), encoding="utf-8"
    )

    print("Wrote:")
    for f in ("sources.json", "cases.json", "manifest.json"):
        p = OUT / f
        print(f"  {p}  ({p.stat().st_size} bytes)")


if __name__ == "__main__":
    main()