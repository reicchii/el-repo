"""
Phantom Worlds — API schemas (Pydantic v2).

Single source of truth for the Frontend and Data Engine teams.

Layering follows `phantom-worlds-ml-research.md` section 6:

    Layer 1  Readings         (no learning; spectrum + derived physicals)
    Layer 2  Experts          (E1..E7, split into spectrum_alone vs all_data)
    Layer 3  Combiner         (gates -> stack -> conformal -> novelty -> explanation)

    Pillar 3/4 Citizen Science (case verification, review, export packets)

All physical quantities carry units in their field names or a sibling ``unit``
field.  An ``origin`` label (Measured | Catalogue | Estimated | Assumed) tags
every number that could be confused for a direct measurement, per section 3
of the research doc.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums / shared literals
# ---------------------------------------------------------------------------

Origin = Literal["Measured", "Catalogue", "Estimated", "Assumed"]
DiscoveryClass = Literal["U1", "U2", "U3", "U4"]
MoleculeKey = Literal["H2O", "CH4", "CO2", "CO"]

# ---------------------------------------------------------------------------
# Layer 1 — Readings
# ---------------------------------------------------------------------------


class SpectralBand(BaseModel):
    """One bin of the 102-band SPHEREx spectrophotometry (0.75–5.0 µm)."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(description="0-based index of the band in the 102-band vector")
    wavelength_um: float = Field(description="Band centre wavelength in microns")
    flux_mjy: Optional[float] = Field(
        default=None, description="Flux density in mJy (None where not covered / flagged)"
    )
    flux_error_mjy: Optional[float] = Field(
        default=None, description="1-sigma flux uncertainty in mJy"
    )
    covered: bool = Field(description="True if the band survived quality / coverage screens")
    band_name: str = Field(description="SPHEREx detector band, e.g. D1..D6")
    flag: Optional[str] = Field(
        default=None, description="Data-quality flag, e.g. 'overflow', 'spacecraft_glow', 'blend'"
    )


class GaiaMetrics(BaseModel):
    """Gaia DR3 detections and the derived physicals written in section 5E."""

    model_config = ConfigDict(extra="forbid")

    source_id: Optional[str] = None
    ra_deg: Optional[float] = None
    dec_deg: Optional[float] = None
    parallax_mas: Optional[float] = None
    pmra_mas_yr: Optional[float] = None
    pmdec_mas_yr: Optional[float] = None
    pm_total_mas_yr: Optional[float] = None
    phot_g_mean_mag: Optional[float] = None
    phot_bp_mean_mag: Optional[float] = None
    phot_rp_mean_mag: Optional[float] = None
    ruwe: Optional[float] = None

    # -- derived physicals -------------------------------------------------
    distance_pc: Optional[float] = Field(
        default=None, description="Distance = 1000 / parallax_mas, in parsecs"
    )
    absolute_magnitude_g: Optional[float] = Field(
        default=None,
        description="M = m + 5*log10(parallax_arcsec) + 5, with parallax_arcsec = parallax_mas/1000",
    )
    tangential_velocity_km_s: Optional[float] = Field(
        default=None, description="4.74 * pm_total_mas_yr / parallax_mas, in km/s"
    )
    parallax_significance: Optional[float] = Field(
        default=None, description="Parallax over its error; set None when the source has no clean Gaia match"
    )


class MoleculeReading(BaseModel):
    """One molecule feature reading (section 3 of the research doc)."""

    model_config = ConfigDict(extra="forbid")

    molecule: MoleculeKey
    feature_label: str = Field(
        description="Human label, e.g. 'Water ice', 'Methane dip', 'Carbon dioxide', 'Carbon monoxide'"
    )
    wavelength_um: float = Field(description="Feature centre in microns")
    value: Optional[float] = Field(
        default=None, description="Reading value; magnitude index for brown dwarfs, optical depth for ice"
    )
    unit: str = Field(description="Unit of `value`, e.g. 'mag' or 'dimensionless'")
    error_16_84: Optional[tuple[float, float]] = Field(
        default=None, description="16th to 84th percentile range from 200 resampled redraws"
    )
    sigma: Optional[float] = Field(default=None, description="Detection significance")
    origin: Origin = Field(description="Origin of the number")
    pct_of_water_ice: Optional[float] = Field(
        default=None, description="Only for ice sightlines: N(mol)/N(H2O) x 100"
    )
    refusal_reason: Optional[str] = Field(
        default=None,
        description=(
            "Set when the reading is refused: blend_share > 0.3, a variable flag is true, "
            "or fewer than 3 bands cover the feature"
        ),
    )


class Readings(BaseModel):
    """Layer 1 — everything shown whether or not any model runs."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    target_name: str
    spectral_bands: list[SpectralBand] = Field(description="The 102-band spectrum")
    coverage_mask: list[bool] = Field(description="102 booleans, convenience copy of band.covered")
    gaia: Optional[GaiaMetrics] = Field(default=None, description="Null when no optical Gaia counterpart exists")
    molecules: list[MoleculeReading] = Field(description="H2O, CH4, CO2, CO readings")
    blend_share: float = Field(description="Blended flux share in [0, 1]; >0.3 refuses molecule readings")
    variable_flag: bool = Field(description="True when the source is flagged variable (NEOWISE / Gaia / SPHEREx visits)")
    notes: str = ""


# ---------------------------------------------------------------------------
# Layer 2 / 3 — ML Identity Panel
# ---------------------------------------------------------------------------


class DecidingBand(BaseModel):
    """One of the top-3 bands that moved the classification (SHAP / template)."""

    model_config = ConfigDict(extra="forbid")

    band_index: int
    wavelength_um: float
    label: str = Field(description="e.g. '3.3 µm measured', '4.3 µm measured', '1.6 µm not measured'")


class PredictionBlock(BaseModel):
    """One stored result. Two are kept per source: spectrum_alone vs all_data."""

    model_config = ConfigDict(extra="forbid")

    experiment: Literal["spectrum_alone", "all_data"]
    experts: list[str] = Field(description="Experts included (E1-E3 vs E1-E7)")
    probabilities: dict[str, float] = Field(description="Calibrated probability per type, best-first")
    top_class: str
    raw_confidence: float = Field(description="Top-class probability before the Honest UI rule")
    display_confidence: float = Field(description="Top-class probability after the Honest UI rule")
    unclassified: bool = Field(description="True when the final confidence falls below 50%")
    conformal_set_90: list[str] = Field(description="Split-conformal 90% prediction set; empty = no known type fits")
    resampled_confidence_range: tuple[float, float] = Field(
        description="[low, high] percent from 100 resampled re-classifications"
    )
    deciding_bands: list[DecidingBand] = Field(description="Top 3 deciding bands")
    e1_top_class: Optional[str] = Field(default=None, description="Template-match (E1) top type")
    e2_top_class: Optional[str] = Field(default=None, description="XGBoost (E2) top type")
    honest_ui_rule_applied: bool = Field(
        description="True when E1 and E2 disagree on top class and confidence was capped at 50%"
    )
    discovery_class: DiscoveryClass
    note: str = ""


class HonestUI(BaseModel):
    """The cross-experiment honesty rule from section 6 of the research doc."""

    model_config = ConfigDict(extra="forbid")

    spectrum_alone_top: str
    all_data_top: str
    agreement: bool = Field(description="True when the two experiments agree on the top type")
    capped_at_50: bool = Field(description="True when E1 (template) and E2 (trees) disagreed and we capped confidence")
    final_label_unclassified: bool


class IdentityPanel(BaseModel):
    """Layer 2 + 3 — the ML identity panel (both stored results + honesty rule)."""

    model_config = ConfigDict(extra="forbid")

    spectrum_alone: PredictionBlock
    all_data: PredictionBlock
    honest_ui: HonestUI


# ---------------------------------------------------------------------------
# Cross-survey flags
# ---------------------------------------------------------------------------


class CrossSurvey(BaseModel):
    """Evidence flags per survey (section 5E). A null value means 'no detection'."""

    model_config = ConfigDict(extra="forbid")

    gaia_match: bool
    gaia_match_note: str = ""
    two_mass_match: Optional[bool] = None
    catwise_match: Optional[bool] = None
    neowise_match: Optional[bool] = None
    simbad_type: Optional[str] = None
    splices_class: Optional[str] = None
    solar_system_object: bool = False


# ---------------------------------------------------------------------------
# Pillar 3 / 4 — Citizen Science (cases, review, export packets)
# ---------------------------------------------------------------------------


class BackyardWorldsPayload(BaseModel):
    """Payload for the Backyard Worlds: Planet 9 (Zooniverse) candidate list."""

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    ra_deg: float
    dec_deg: float
    w1_mag: Optional[float] = None
    w2_mag: Optional[float] = None
    w1_w2_color: Optional[float] = None
    proper_motion_mas_yr: Optional[float] = None
    spectral_type_guess: Optional[str] = None
    notes: str = ""


class AAVSOVSXPayload(BaseModel):
    """Payload for the AAVSO Variable Star Index (VSX)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    ra_deg: float
    dec_deg: float
    variability_type: str = Field(description="VSX variability class code, e.g. 'M', 'T', 'FLARE', 'EA'")
    period_days: Optional[float] = None
    epoch_mjd: Optional[float] = None
    mag_min: Optional[float] = None
    mag_max: Optional[float] = None
    band: str = "V"
    notes: str = ""


class MPCADESPayload(BaseModel):
    """Payload in the Minor Planet Center ADES format (solar-system objects only)."""

    model_config = ConfigDict(extra="forbid")

    obs_time_utc: str
    ra_deg: float
    dec_deg: float
    mag: Optional[float] = None
    band: str = "V"
    observatory_code: str
    notes: str = ""


class ExportPackets(BaseModel):
    """Export packet payloads — one block per destination registry."""

    model_config = ConfigDict(extra="forbid")

    backyard_worlds: Optional[BackyardWorldsPayload] = None
    aavso_vsx: Optional[AAVSOVSXPayload] = None
    mpc_ades: Optional[MPCADESPayload] = None


class CaseRecord(BaseModel):
    """Pillar 3/4 — a citizen-science verification case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    source_id: str
    target_name: str
    verification_stage: int = Field(ge=1, le=6, description="1 auto -> 2 nominated -> 3 open -> 4 consensus -> 5 confirmed -> 6 exported")
    discovery_class: DiscoveryClass
    blind_review_vote_tally: dict[str, int] = Field(description="Type -> raw reviewer votes")
    spectral_reputation_weight: float = Field(
        ge=0.0, le=1.0,
        description="Aggregate reviewer weight from the O-to-Y spectral-type reputation ladder",
    )
    forum_unlock_status: bool
    export_packets: ExportPackets
    notes: str = ""


# ---------------------------------------------------------------------------
# Top-level records
# ---------------------------------------------------------------------------


class SourceRecord(BaseModel):
    """A fully-typed source: readings + identity panel + cross-survey flags."""

    model_config = ConfigDict(extra="forbid")

    target_name: str
    source_id: str
    readings: Readings
    identity: IdentityPanel
    cross_surveys: CrossSurvey


class Manifest(BaseModel):
    """Bundle metadata so the frontend can discover and validate the packs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    generated_at: str
    project: str
    challenge: str
    targets: list[str]
    source_count: int
    case_count: int
    band_count: int
    band_wavelength_range_um: tuple[float, float]
    sources_file: str
    cases_file: str
    discovery_class_legend: dict[str, str] = Field(
        description="U1..U4 working definitions (see generate_sample_packs.py for provenance)"
    )
    notes: list[str] = []


__all__ = [
    "SpectralBand",
    "GaiaMetrics",
    "MoleculeReading",
    "Readings",
    "DecidingBand",
    "PredictionBlock",
    "HonestUI",
    "IdentityPanel",
    "CrossSurvey",
    "BackyardWorldsPayload",
    "AAVSOVSXPayload",
    "MPCADESPayload",
    "ExportPackets",
    "CaseRecord",
    "SourceRecord",
    "Manifest",
]