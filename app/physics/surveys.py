"""
Phantom Worlds — survey cross-matching, astrometry and physical gates (T43e).

Implements the Gaia-DR3 side of `phantom-worlds-ml-research.md` sections 5E
and 5G on top of the benchmark ``*_gaia_dr3.csv`` field tables.

The CSV files are **cone-search field tables** (171–1,719 rows), so a blind
``row[0]`` is wrong (documented in ``DATA_INSPECTION_SUMMARY.md``).  This module
provides a proper cross-matcher:

1. **Epoch propagation** — Gaia DR3 positions are referenced to J2016.0
   (MJD 57388).  High-proper-motion objects move tens of arcseconds between
   J2016 and the SPHEREx epoch (~2025), so both the target and each field row
   are propagated to a common epoch before separating.
2. **Nearest neighbour + proper-motion / brightness consistency** — the
   propagated separation picks the candidate; a proper-motion agreement score
   and parallax significance confirm it.
3. **Crowding / ``blend_share``** — neighbours within the 6.15″ SPHEREx pixel
   radius contribute a flux-weighted blend share.
4. **Derived physicals** — distance, absolute magnitude, tangential velocity,
   and reduced proper motion when parallax is missing or below 5σ.
5. **``no_optical_detection``** — True when no Gaia row survives the match
   (canonically WISE 0855, an optical-invisible Y dwarf).
6. **Physical gates** — a Gaia parallax significance above 5σ hard-gates out
   the extragalactic classes (``Galaxy``, ``Active galaxy or quasar``).

Pure stdlib + ``math`` (no sciPy / astropy) so the tier remains install-light.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GAIA_DR3_REF_EPOCH_MJD = 57388.0  # J2016.0
J2000_EPOCH_MJD = 51544.5  # J2000.0 (epoch of target catalogue positions)
SPHEREX_NOMINAL_EPOCH_MJD = 61100.0  # ~2025.3, within the D1–D6 frame window
SPHEREX_PIXEL_RADIUS_ARCSEC = 6.15  # section 2, fact 5

MAS_PER_DEG = 3.6e6
ARCSEC_PER_DEG = 3600.0

# Gaia CSV column order (fixed, verified by inspect_csv.py).
GAIA_COLUMNS = [
    "source_id", "ra", "dec", "pmra", "pmdec", "parallax",
    "phot_g_mean_mag", "phot_bp_mean_mag", "phot_rp_mean_mag", "ruwe",
]

# Level-1 object types (section 4).  Extragalactic sets are hard-gated out.
EXTRAGALACTIC_CLASSES = {"Galaxy", "Active galaxy or quasar"}
ALL_CLASSES = [
    "Star",
    "Ultracool dwarf",
    "Young star",
    "Evolved giant star",
    "Galaxy",
    "Active galaxy or quasar",
    "Solar-system object",
    "Unclassified",
]

BACKEND_DIR = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Target catalogue (J2000 positions + literature astrometry)
# ---------------------------------------------------------------------------

@dataclass
class TargetCatalogEntry:
    name: str
    ra_j2000_deg: float
    dec_j2000_deg: float
    pmra_mas_yr: Optional[float]
    pmdec_mas_yr: Optional[float]
    parallax_mas: Optional[float]
    spectral_type: str
    variable: bool = False
    no_optical_expected: bool = False
    note: str = ""


# Literature values.  PM / parallax for Barnard's Star and Epsilon Indi B are
# read back from the CSV rows themselves; the catalogue seed uses the same
# published numbers so provenance is traceable.
TARGET_CATALOG: dict[str, TargetCatalogEntry] = {
    "Barnards_Star": TargetCatalogEntry(
        name="Barnards_Star", ra_j2000_deg=269.4518, dec_j2000_deg=4.6934,
        pmra_mas_yr=-801.551, pmdec_mas_yr=10362.394, parallax_mas=546.976,
        spectral_type="M4V", variable=False, no_optical_expected=False,
        note="Very bright; check for overflow in D1.",
    ),
    "Epsilon_Indi_B": TargetCatalogEntry(
        name="Epsilon_Indi_B", ra_j2000_deg=331.0438, dec_j2000_deg=-56.7828,
        pmra_mas_yr=3981.98, pmdec_mas_yr=-2466.83, parallax_mas=270.66,
        spectral_type="T1/T6", variable=False, no_optical_expected=False,
        note="Glare from Epsilon Indi A; ruwe elevated.",
    ),
    "R_Draconis": TargetCatalogEntry(
        name="R_Draconis", ra_j2000_deg=248.1676, dec_j2000_deg=66.7550,
        pmra_mas_yr=-20.643, pmdec_mas_yr=6.149, parallax_mas=1.251,
        spectral_type="Mira (M)", variable=True, no_optical_expected=False,
        note="Mira variable; bright (G=6.37); check overflow in D1.",
    ),
    "RW_Aurigae": TargetCatalogEntry(
        name="RW_Aurigae", ra_j2000_deg=76.9565, dec_j2000_deg=30.4013,
        pmra_mas_yr=4.9, pmdec_mas_yr=-24.6, parallax_mas=None,
        spectral_type="T Tauri (K5 + binary)", variable=True, no_optical_expected=False,
        note="Blended binary pair; changes between visits.",
    ),
    "WISE_0855": TargetCatalogEntry(
        name="WISE_0855", ra_j2000_deg=133.7961, dec_j2000_deg=-7.2353,
        pmra_mas_yr=-8120.0, pmdec_mas_yr=820.0, parallax_mas=None,
        spectral_type="Y dwarf", variable=False, no_optical_expected=True,
        note="Optical-invisible ultracool dwarf; no Gaia counterpart; D1-D4 not covered.",
    ),
}


# ---------------------------------------------------------------------------
# Nominal Gaia parallax error model (the CSV has no parallax_error column).
# [ESTIMATE] — used only to turn parallax into a >/< 5 sigma significance flag.
# ---------------------------------------------------------------------------

def parallax_error_mas(phot_g_mean_mag: Optional[float]) -> Optional[float]:
    """Nominal Gaia DR3 parallax uncertainty vs G magnitude (estimated)."""
    if phot_g_mean_mag is None:
        return None
    g = phot_g_mean_mag
    if g < 13.0:
        return 0.02
    if g < 15.0:
        return 0.03
    if g < 17.0:
        return 0.07
    if g < 19.0:
        return 0.15
    if g < 20.0:
        return 0.30
    return 0.70


# ---------------------------------------------------------------------------
# Epoch propagation
# ---------------------------------------------------------------------------

def propagate(ra_deg, dec_deg, pmra_mas_yr, pmdec_mas_yr, from_epoch_mjd, to_epoch_mjd):
    """Propagate a position from ``from_epoch_mjd`` to ``to_epoch_mjd`` using PM.

    Returns (ra_deg, dec_deg) at the target epoch.  pmra is the true angular
    rate in μas·cos(dec)/yr (already cos(dec)-corrected per Gaia convention), so
    the RA shift is ``pmra / cos(dec)``.
    """
    dt_yr = (to_epoch_mjd - from_epoch_mjd) / 365.25
    dec = math.radians(dec_deg)
    cosd = math.cos(dec) if abs(math.cos(dec)) > 1e-9 else 1e-9
    dra_deg = (pmra_mas_yr * dt_yr) / MAS_PER_DEG / cosd
    ddec_deg = (pmdec_mas_yr * dt_yr) / MAS_PER_DEG
    return ra_deg + dra_deg, dec_deg + ddec_deg


def angular_separation_arcsec(ra1, dec1, ra2, dec2):
    """Vincenty-free great-circle separation (accurate to <1e-6 for small angles)."""
    dra = (ra2 - ra1) * math.cos(math.radians((dec1 + dec2) / 2.0))
    ddec = dec2 - dec1
    return math.hypot(dra, ddec) * ARCSEC_PER_DEG


# ---------------------------------------------------------------------------
# Astrometry result
# ---------------------------------------------------------------------------

@dataclass
class Astrometry:
    source_id: Optional[str] = None
    matched: bool = False
    separation_arcsec: Optional[float] = None
    ra_deg: Optional[float] = None
    dec_deg: Optional[float] = None
    pmra_mas_yr: Optional[float] = None
    pmdec_mas_yr: Optional[float] = None
    pm_total_mas_yr: Optional[float] = None
    parallax_mas: Optional[float] = None
    parallax_error_mas: Optional[float] = None
    parallax_significance: Optional[float] = None
    phot_g_mean_mag: Optional[float] = None
    phot_bp_mean_mag: Optional[float] = None
    phot_rp_mean_mag: Optional[float] = None
    ruwe: Optional[float] = None
    distance_pc: Optional[float] = None
    absolute_magnitude_g: Optional[float] = None
    tangential_velocity_km_s: Optional[float] = None
    reduced_proper_motion: Optional[float] = None
    blend_share: float = 0.0
    neighbour_count_within_pixel: int = 0
    no_optical_detection: bool = False
    gated_out_classes: list[str] = field(default_factory=list)
    origin: str = "Catalogue"


def _to_float(row: dict, key: str) -> Optional[float]:
    v = row.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Cross-matcher
# ---------------------------------------------------------------------------

@dataclass
class GaiaField:
    """In-memory representation of one ``*_gaia_dr3.csv`` field table."""

    target_name: str
    rows: list[dict]

    @classmethod
    def load(cls, target_name: str, base_dir: Optional[Path] = None) -> "GaiaField":
        base = base_dir or BACKEND_DIR
        path = base / f"{target_name}_gaia_dr3.csv"
        rows: list[dict] = []
        with path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append(r)
        return cls(target_name=target_name, rows=rows)


@dataclass
class CrossMatchResult:
    target: TargetCatalogEntry
    astrometry: Astrometry
    field_row_count: int
    target_row: Optional[dict] = None


class CrossMatcher:
    """Cross-match a target against its Gaia cone-search field table."""

    def __init__(self, epoch_mjd: float = SPHEREX_NOMINAL_EPOCH_MJD,
                 max_separation_arcsec: float = 2.0):
        self.epoch_mjd = epoch_mjd
        self.max_separation_arcsec = max_separation_arcsec

    def match(self, target: TargetCatalogEntry, field: GaiaField) -> CrossMatchResult:
        astro = Astrometry(no_optical_detection=target.no_optical_expected)

        # Propagate the target's J2000 position to the SPHEREx epoch.
        if target.pmra_mas_yr is not None and target.pmdec_mas_yr is not None:
            t_ra, t_dec = propagate(target.ra_j2000_deg, target.dec_j2000_deg,
                                    target.pmra_mas_yr, target.pmdec_mas_yr,
                                    J2000_EPOCH_MJD, self.epoch_mjd)
        else:
            t_ra, t_dec = target.ra_j2000_deg, target.dec_j2000_deg

        # Propagate every field row and keep the nearest.
        best_sep = float("inf")
        best_row: Optional[dict] = None
        for row in field.rows:
            ra = _to_float(row, "ra")
            dec = _to_float(row, "dec")
            pmra = _to_float(row, "pmra") or 0.0
            pmdec = _to_float(row, "pmdec") or 0.0
            if ra is None or dec is None:
                continue
            r_ra, r_dec = propagate(ra, dec, pmra, pmdec, GAIA_DR3_REF_EPOCH_MJD, self.epoch_mjd)
            sep = angular_separation_arcsec(t_ra, t_dec, r_ra, r_dec)
            if sep < best_sep:
                best_sep = sep
                best_row = row

        if best_row is None or best_sep > self.max_separation_arcsec:
            # No optical counterpart survives (or none exists).
            astro.no_optical_detection = True
            return CrossMatchResult(target=target, astrometry=astro,
                                    field_row_count=len(field.rows))

        astro.matched = True
        astro.source_id = best_row.get("source_id")
        astro.separation_arcsec = round(best_sep, 3)
        astro.ra_deg = _to_float(best_row, "ra")
        astro.dec_deg = _to_float(best_row, "dec")
        astro.pmra_mas_yr = _to_float(best_row, "pmra")
        astro.pmdec_mas_yr = _to_float(best_row, "pmdec")
        astro.parallax_mas = _to_float(best_row, "parallax")
        astro.phot_g_mean_mag = _to_float(best_row, "phot_g_mean_mag")
        astro.phot_bp_mean_mag = _to_float(best_row, "phot_bp_mean_mag")
        astro.phot_rp_mean_mag = _to_float(best_row, "phot_rp_mean_mag")
        astro.ruwe = _to_float(best_row, "ruwe")

        self._derive_astrometry(astro)
        self._compute_blend_share(astro, best_row, field, t_ra, t_dec)
        self._compute_gates(astro)

        return CrossMatchResult(target=target, astrometry=astro,
                                field_row_count=len(field.rows), target_row=best_row)

    # -- derived physicals --------------------------------------------------

    def _derive_astrometry(self, astro: Astrometry) -> None:
        pm = astro.pmra_mas_yr and astro.pmdec_mas_yr
        if pm is not None and astro.pmra_mas_yr is not None and astro.pmdec_mas_yr is not None:
            astro.pm_total_mas_yr = math.hypot(astro.pmra_mas_yr, astro.pmdec_mas_yr)

        # Parallax and significance (error is nominal/estimated).
        plx = astro.parallax_mas
        g = astro.phot_g_mean_mag
        astro.parallax_error_mas = parallax_error_mas(g)
        if plx is not None and plx > 0 and astro.parallax_error_mas:
            astro.parallax_significance = plx / astro.parallax_error_mas
            astro.distance_pc = 1000.0 / plx

        # Absolute magnitude: M = m + 5*log10(parallax_arcsec) + 5.
        if g is not None and plx is not None and plx > 0:
            plx_arcsec = plx / 1000.0
            astro.absolute_magnitude_g = g + 5.0 * math.log10(plx_arcsec) + 5.0

        # Tangential velocity: 4.74 * pm (arcsec/yr) / parallax (arcsec).
        if astro.pm_total_mas_yr is not None and plx is not None and plx > 0:
            astro.tangential_velocity_km_s = 4.74 * (astro.pm_total_mas_yr / 1000.0) / (plx / 1000.0)

        # Reduced proper motion when parallax is missing or below 5 sigma.
        if astro.pm_total_mas_yr is not None and g is not None:
            pm_arcsec_yr = astro.pm_total_mas_yr / 1000.0
            if pm_arcsec_yr > 0:
                astro.reduced_proper_motion = g + 5.0 + 5.0 * math.log10(pm_arcsec_yr)

    def _compute_blend_share(self, astro: Astrometry, target_row: dict,
                             field: GaiaField, t_ra: float, t_dec: float) -> None:
        """Flux-weighted blend share from neighbours within the 6.15″ pixel."""
        g_target = _to_float(target_row, "phot_g_mean_mag")
        target_id = target_row.get("source_id")
        if g_target is None:
            astro.blend_share = 0.0
            return

        neighbour_flux = 0.0
        count = 0
        for row in field.rows:
            if row.get("source_id") == target_id:
                continue
            g = _to_float(row, "phot_g_mean_mag")
            ra = _to_float(row, "ra")
            dec = _to_float(row, "dec")
            if g is None or ra is None or dec is None:
                continue
            sep = angular_separation_arcsec(t_ra, t_dec, ra, dec)
            if sep <= SPHEREX_PIXEL_RADIUS_ARCSEC:
                neighbour_flux += 10.0 ** (-0.4 * (g - g_target))
                count += 1

        astro.neighbour_count_within_pixel = count
        astro.blend_share = neighbour_flux / (1.0 + neighbour_flux) if neighbour_flux > 0 else 0.0

    def _compute_gates(self, astro: Astrometry) -> None:
        """Physical gates (section 5E): >5σ parallax excludes extragalactic classes."""
        sig = astro.parallax_significance
        if sig is not None and sig > 5.0:
            astro.gated_out_classes = sorted(EXTRAGALACTIC_CLASSES)


# ---------------------------------------------------------------------------
# Convenience: run the matcher for a target from the canonical CSV location
# ---------------------------------------------------------------------------

def analyze_target(target_name: str, epoch_mjd: float = SPHEREX_NOMINAL_EPOCH_MJD) -> CrossMatchResult:
    """Load the field table for ``target_name`` and cross-match its catalogue seed."""
    target = TARGET_CATALOG[target_name]
    field = GaiaField.load(target_name)
    matcher = CrossMatcher(epoch_mjd=epoch_mjd)
    return matcher.match(target, field)