# Data Inspection Summary — Phantom Worlds Backend

**To:** Akbar, Tata, Hendro
**From:** Lead Backend & ML Engineer
**Topic:** What the 10 benchmark CSVs actually contain, and the one pitfall to avoid

---

## TL;DR

The `*_gaia_dr3.csv` files are **cone-search field tables**, not single-target
rows. **Do not take row 0 blindly** — you must cross-match by sky position and
proper motion to find the actual target (or determine that no match exists).

| Target | Gaia CSV rows | SPHEREx frames | Gaia conclusion |
|---|---|---|---|
| Barnard's Star | 1,719 | 387 (515.8 d) | ✅ real match: `source_id 4472832130942575872`, parallax 546.98 mas |
| Epsilon Indi B | 175 | 487 (525.6 d) | ✅ real match: `source_id 6412596012146801152`, parallax 270.66 mas |
| R Draconis | 128 | 2,588 (520.4 d) | ⚠️ no high-significance parallax (distant Mira variable) |
| RW Aurigae | 769 | 343 (510.1 d) | ⚠️ blended binary pair, no parallax > 20 mas |
| WISE 0855 | 194 | 264 (384.6 d) | ❌ **no optical counterpart** (Y-dwarf, invisible in Gaia's bands) |

---

## 1. Why the row counts vary (171 → 1,719)

Each Gaia file is the result of a **cone search** around the target's J2000
coordinates, so it contains *every* Gaia DR3 source inside that radius, ordered
however the query returned them. Bright, well-studied fields (Barnard's Star)
capture more rows than sparse fields (R Draconis). The counts are **not** a
property of the target itself.

The SPHEREx files are the analogous query on the SPHEREx DR1 frame/level-2
metadata (`obs_id`s, one row per detector-bandpass exposure), which is why they
run to hundreds or thousands of rows.

## 2. The cross-match rules

The actual target is identified by **nearest-neighbour + proper-motion
cross-match**, not by array index.

- **Barnard's Star** — unambiguous: a single source with parallax = 546.98 mas
  (3.5 pc) and proper motion ≈ 10,393 mas/yr, the known Barnard's Star PM.
- **Epsilon Indi B** — single high-PM source (parallax 270.66 mas, pmra ~3982 /
  pmdec ~−2467 mas/yr), though `ruwe=4.30` warns the astrometry is uneasy
  (glare from Epsilon Indi A).
- **R Draconis** — no clean parallax (max 2.50 mas is a background field star).
  R Dra is ~1.9 kpc away, so its parallax is ~0.5 mas and lost in the errors.
  Treat as *photometry available, distance from literature*.
- **RW Aurigae** — it's a binary T Tauri system; the nearest rows are the
  resolved/blended pair, none with `parallax > 20 mas`. Treat as
  *no reliable Gaia parallax*.
- **WISE 0855** — 194 rows all are background Gaia objects in the direction of
  the Y dwarf. **None is the target.** WISE 0855-0714 is below Gaia's optical
  detection limit; its parallax (~100 mas) comes from WISE/absolute-brightness
  arguments, not Gaia.

## 3. SPHEREx bandpasses (real, from the frames CSVs)

All five targets share the same six detector bandpasses (one "SPHEREx" wrapper
row + one per exposure):

| Detector | λ range (µm) | Resolving power |
|---|---|---|
| D1 | 0.745–1.117 | 39.1 |
| D2 | 1.103–1.650 | 41.4 |
| D3 | 1.630–2.435 | 40.6 |
| D4 | 2.403–3.847 | 34.9 |
| D5 | 3.811–4.430 | 111.6 |
| D6 | 4.412–5.010 | 127.8 |

The 102-band product used in our schemas is the 6 × 17 equal-width binning of
the official SPHEREx channels across this 0.75–5.0 µm range.

## 4. Guideline for Data Engine / pipeline work

1. When consuming `*_gaia_dr3.csv`, **always run your own cross-match**: build a
   sky-position index (or use `astropy.coordinates.SkyCoord.match_to_catalog_sky`),
   then rank by angular separation **and** proper-motion agreement.
2. If `parallax/parallax_error < 5`, treat it as **no parallax** → fall back to
   reduced proper motion or literature distance (research doc §5E).
3. When no Gaia source survives the match within a few arcsec of the target's
   known position, record `gaia_match = false` and keep the source as
   *IR-only*. WISE 0855 is the canonical case.
4. Re-check the Gaia row identities against the numbers above before wiring
   them into the pipeline — the "obvious" brightest row is **not** always the
   target (see RW Aurigae).

The full machine-readable inventory is in
[`csv_inspection_report.json`](./csv_inspection_report.json), and the generator
that produced the sample packs is
[`generate_sample_packs.py`](./generate_sample_packs.py).