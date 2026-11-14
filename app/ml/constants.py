"""Shared constants for the Phantom Worlds ML tier.

The 102-band grid reproduces ``generate_sample_packs.build_band_boundaries``
exactly (verified against the frozen ``sample_packs/sources.json``), so every
synthetic spectrum and every feature vector shares the same wavelength bins as
the five benchmark targets.
"""

from __future__ import annotations

# -- 102-band grid -----------------------------------------------------------

N_BANDS = 102


def _build_grid() -> tuple[list[float], list[str]]:
    """Return (wavelengths_um, detector_names) for the 102 SPHEREx bands."""
    channels = [
        ("D1", 0.75, 1.11, 17),
        ("D2", 1.11, 1.65, 17),
        ("D3", 1.65, 2.43, 17),
        ("D4", 2.43, 3.85, 17),
        ("D5", 3.85, 4.43, 17),
        ("D6", 4.43, 5.00, 17),
    ]
    wl: list[float] = []
    det: list[str] = []
    for name, lo, hi, n in channels:
        for i in range(n):
            b_lo = lo + (hi - lo) * i / n
            b_hi = lo + (hi - lo) * (i + 1) / n
            wl.append(round((b_lo + b_hi) / 2.0, 4))
            det.append(name)
    return wl, det


WAVELENGTHS_UM, DETECTORS = _build_grid()

DETECTOR_NAMES = ["D1", "D2", "D3", "D4", "D5", "D6"]

# -- object types ------------------------------------------------------------

# Level 1 classes the type model is trained to recognise.  "Young star" is the
# short form used across the schemas; the full phrase in the research doc is
# "Young star with ice or dust".
LEVEL1_CLASSES = [
    "Star",
    "Ultracool dwarf",
    "Young star",
    "Evolved giant star",
    "Galaxy",
    "Active galaxy or quasar",
]

CLASS_TO_INT = {c: i for i, c in enumerate(LEVEL1_CLASSES)}
INT_TO_CLASS = {i: c for c, i in CLASS_TO_INT.items()}

# Level 2 subtypes for ultracool dwarfs (L0..L9, T0..T9, Y0..Y1).
ULTRA_COOL_SUBTYPES = [f"L{i}" for i in range(10)] + [f"T{i}" for i in range(10)] + ["Y0", "Y1"]


def subtype_index(subtype: str | None) -> int:
    """Ordinal position in the L0..Y1 ladder (for template continuity)."""
    if subtype is None:
        return -1
    return ULTRA_COOL_SUBTYPES.index(subtype)


# -- contamination flags (a flagged band is dropped from the type features) ---
CONTAMINATION_FLAGS = {
    "spacecraft_glow_suspected",
    "overflow",
    "overflow_suspected",
    "blend",
    "non_detection_upper_limit",
}

# -- discovery ontology (Section 4 / Pillar 3-4) -----------------------------

# U1..U4 as implemented by M3.  Updated from the Step-1 placeholder wording to
# match the brief's explicit four meanings.
DISCOVERY_LEGEND = {
    "U1": "Uncatalogued — no Gaia optical counterpart; detected only via IR moving source / D5-D6 residual",
    "U2": "Untyped Dot — spectrum-only type awaiting independent multi-survey corroboration",
    "U3": "Wrong Label — model type disagrees with the existing catalogue label",
    "U4": "New Behavior — 102-colour visit-to-visit variability not explained by existing taxa",
}

# -- Pillar 3/4 spectral reputation ladder (O -> Y, 0.00 to 0.92) --------------
# A reviewer's spectral "class" maps to a vote weight.  O astronomers and Y
# specialists would be odd, but the ladder is exactly as specified in the brief.
SPECTRAL_REPUTATION_WEIGHT = {
    "O": 0.00,
    "B": 0.10,
    "A": 0.20,
    "F": 0.30,
    "G": 0.40,
    "K": 0.50,
    "M": 0.60,
    "L": 0.70,
    "T": 0.80,
    "Y": 0.92,
}

# -- release gates (Section 9) -----------------------------------------------
PASS_MARKS = {
    "level1_recall": 0.80,          # per-type recall on gold labels, S/N > 10
    "calibration_error_max": 0.05,  # ECE ceiling
    "conformal_low": 0.88,          # 90% sets must cover 88%..92%
    "conformal_high": 0.92,
    "subtype_within_2_frac": 0.80,  # ultracool subtype within 2 subtypes
}

# Random seed for reproducible synthetic data and model training.
SEED = 20261114