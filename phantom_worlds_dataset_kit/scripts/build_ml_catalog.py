"""
Build a curated, multi-class astronomical target catalog for SPHEREx + Gaia ML training
and batch downloading, grounded in the sources listed in `phantom-worlds-ml-research.md`:
  - SPIFF Ultracool Dwarf table (Zenodo 10.5281/zenodo.19051216)
  - IRSA SPLICES v8.6 catalog via Gator (`irsa.ipac.caltech.edu`)
  - ESA Gaia DR3 TAP (`gea.esac.esa.int`) QSO, Galaxy, YSO, LPV, and Field Star tables

Outputs an interleaved, spatially deduplicated CSV directly compatible with:
    python phantom_worlds_dataset_kit/scripts/download_real_spherex_gaia.py --targets-csv ...
"""

import argparse
from collections import defaultdict
import csv
import io
import math
import os
import re
import sys
import zipfile

from astropy import units as u
from astropy.coordinates import SkyCoord

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from phantom_worlds.contracts import HardenedHTTPSession, validate_remote_url

ALLOWED_CATALOG_HOSTS = frozenset({"irsa.ipac.caltech.edu", "gea.esac.esa.int", "zenodo.org"})
SPIFF_TABLES_URL = "https://zenodo.org/api/records/19051216/files/spiff_tables.zip/content"
SPIFF_MEMBER_NAME = "spiff_tables/spherex_autotype_datasets_fulltable.csv"
IRSA_GATOR_URL = "https://irsa.ipac.caltech.edu/cgi-bin/Gator/nph-query"
ESA_GAIA_TAP_SYNC_URL = "https://gea.esac.esa.int/tap-server/tap/sync"

DEFAULT_OUT_CSV = os.path.join(ROOT_DIR, "phantom_worlds_dataset_kit", "csv_tables", "curated_ml_targets.csv")
_MAX_ZIP_BYTES = 20 * 1024 * 1024
_MAX_CSV_BYTES = 30 * 1024 * 1024

LEVEL1_CLASSES = (
    "Ultracool dwarf",
    "Young star with ice or dust",
    "Evolved giant star",
    "Star",
    "Active galaxy or quasar",
    "Galaxy",
)

SPLICES_FIELDS = (
    ("Orion", "83.822 -5.391", "1800"),
    ("Taurus", "68.0 +25.0", "3600"),
    ("Ophiuchus", "246.8 -24.4", "2400"),
    ("CygnusX", "308.0 +41.0", "1800"),
    ("Carina", "161.2 -59.7", "1800"),
    ("GalPlane", "290.0 +0.0", "1800"),
)

_SPIFF_DATASET_RANK = {
    "Known": 0,
    "New Discoveries": 1,
    "Known Candidates": 2,
    "New Candidates": 3,
}
_UCD_SPT_RE = re.compile(r"^(?:M[789]|L\d|T\d|Y\d|d?[LT]\d|sd[LT]\d)", re.IGNORECASE)
_UNSAFE_NAME_CHARS_RE = re.compile(r"[^A-Za-z0-9_.-]+")

CSV_FIELDNAMES = (
    "target_name",
    "ra_deg",
    "dec_deg",
    "pmra",
    "pmdec",
    "ref_epoch",
    "ml_class",
    "subclass",
    "label_source",
    "label_grade",
    "source_id",
)


def _new_catalog_session(timeout=60):
    return HardenedHTTPSession(timeout=timeout, allowed_hosts=ALLOWED_CATALOG_HOSTS)


def _safe_float(val, default=None):
    if val is None:
        return default
    text = str(val).strip()
    if not text or text.lower() in ("null", "nan", "na", "none"):
        return default
    num = float(text)
    return num if math.isfinite(num) else default


def _sanitize_target_name(raw_name):
    cleaned = str(raw_name or "").replace("+", "p").replace(" ", "_")
    cleaned = _UNSAFE_NAME_CHARS_RE.sub("_", cleaned).strip("._")
    while ".." in cleaned:
        cleaned = cleaned.replace("..", "_")
    cleaned = cleaned[:64]
    if not cleaned:
        raise ValueError(f"Cannot build safe target_name from {raw_name!r}")
    return cleaned


def _read_bounded_bytes(resp, max_bytes):
    content_len = getattr(resp, "headers", {}).get("Content-Length")
    if content_len is not None:
        try:
            if int(content_len) > max_bytes:
                raise ValueError(f"Catalog payload exceeded {max_bytes} byte limit")
        except (TypeError, ValueError) as exc:
            if "exceeded" in str(exc):
                raise
    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"Catalog stream exceeded {max_bytes} byte limit")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_spiff_ultracool_dwarfs(session=None, url=SPIFF_TABLES_URL, max_rows=400):
    """Download Zenodo SPIFF ultracool dwarf autotype table in RAM and extract verified L/T/Y/late-M targets."""
    safe_url = validate_remote_url(url, allowed_hosts=ALLOWED_CATALOG_HOSTS, allow_query=True)
    own_sess = session is None
    sess = _new_catalog_session(timeout=45) if own_sess else session
    try:
        with sess.get(safe_url, timeout=45, allow_redirects=False, stream=True) as resp:
            resp.raise_for_status()
            zip_bytes = _read_bounded_bytes(resp, _MAX_ZIP_BYTES)
    finally:
        if own_sess:
            sess.close()

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        safe_members = [
            info for info in zf.infolist()
            if not info.is_dir() and not info.filename.startswith("/") and ".." not in info.filename
        ]
        if any(info.filename.startswith("/") or ".." in info.filename for info in zf.infolist()):
            raise ValueError("Unsafe path traversal entry inside SPIFF zip archive")
        target_info = next((info for info in safe_members if info.filename == SPIFF_MEMBER_NAME), None)
        if target_info is None:
            raise ValueError(f"Missing expected SPIFF member {SPIFF_MEMBER_NAME!r}")
        if target_info.file_size > _MAX_CSV_BYTES:
            raise ValueError(f"SPIFF table exceeds {_MAX_CSV_BYTES} byte cap")
        raw_csv = zf.read(target_info)[: _MAX_CSV_BYTES + 1]
        if len(raw_csv) > _MAX_CSV_BYTES:
            raise ValueError(f"SPIFF table stream exceeds {_MAX_CSV_BYTES} byte cap")

    raw_rows = list(csv.DictReader(io.StringIO(raw_csv.decode("utf-8"))))
    filtered = []
    for row in raw_rows:
        spt = (row.get("spiff_autotype") or "").strip()
        if not _UCD_SPT_RE.match(spt):
            continue
        dataset = (row.get("dataset") or "").strip()
        chi2 = _safe_float(row.get("spiff_chi2_r"), 999.0)
        filtered.append((
            _SPIFF_DATASET_RANK.get(dataset, 9),
            chi2,
            (row.get("designation") or "").strip(),
            row,
        ))
    filtered.sort(key=lambda item: item[:3])
    selected = [item[3] for item in filtered[:max_rows]]
    if not selected:
        return []

    coords = SkyCoord(
        [r["ra_j2000"] for r in selected],
        [r["dec_j2000"] for r in selected],
        unit=(u.hourangle, u.deg),
        frame="icrs",
    )
    out = []
    for row, coord in zip(selected, coords):
        desig = (row.get("designation") or "").strip()
        spt = (row.get("spiff_autotype") or "").strip()
        dataset = (row.get("dataset") or "").strip()
        out.append({
            "target_name": _sanitize_target_name(f"SPIFF_{desig}"),
            "ra_deg": round(float(coord.ra.deg), 6),
            "dec_deg": round(float(coord.dec.deg), 6),
            "pmra": 0.0,
            "pmdec": 0.0,
            "ref_epoch": 2000.0,
            "ml_class": "Ultracool dwarf",
            "subclass": spt,
            "label_source": f"SPIFF_Zenodo_19051216:{dataset}",
            "label_grade": "gold" if dataset in ("Known", "New Discoveries") else "silver",
            "source_id": desig,
        })
    return out


def parse_ipac_ascii_table(text):
    """Parse IRSA Gator `outfmt=1` IPAC ASCII table rows into dicts, mapping `null` to empty strings."""
    lines = text.splitlines()
    header_line = next((ln for ln in lines if ln.startswith("|") and "designation" in ln), None)
    if not header_line:
        return []
    headers = [col.strip() for col in header_line.split("|")[1:-1]]
    rows = []
    for line in lines:
        if not line.strip() or line.startswith("\\") or line.startswith("|"):
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) != len(headers):
            continue
        rows.append({
            hdr: ("" if val.strip().lower() == "null" else val.strip())
            for hdr, val in zip(headers, parts)
        })
    return rows


def _classify_splices_row(row):
    class_1 = (row.get("class_1") or "").strip()
    stype_ml = (row.get("stype_ml") or "").strip()
    prob1 = _safe_float(row.get("stype_ml_prob1"), 0.0)
    var_gaia = (row.get("varclassgaia") or "").strip()

    if class_1 in ("YSO_D", "YSO_P", "YSO_F"):
        return "Young star with ice or dust", class_1, "gold"
    if "YSO" in stype_ml and prob1 >= 0.85:
        return "Young star with ice or dust", stype_ml, "silver"
    if stype_ml in ("C AGB", "O AGB") and prob1 >= 0.85:
        return "Evolved giant star", stype_ml, "silver"
    if var_gaia == "LPV":
        return "Evolved giant star", "LPV", "silver"
    if stype_ml == "MS Star" and prob1 >= 0.90:
        return "Star", "MS_Star", "silver"
    if stype_ml == "AGN" and prob1 >= 0.90:
        return "Active galaxy or quasar", "AGN", "silver"
    return None, None, None


def fetch_irsa_splices_targets(session=None, fields=SPLICES_FIELDS, per_class_cap=300):
    """Query IRSA SPLICES via Gator cones for YSOs, AGB evolved giants, MS stars, and AGN."""
    safe_url = validate_remote_url(IRSA_GATOR_URL, allowed_hosts=ALLOWED_CATALOG_HOSTS, allow_query=True)
    own_sess = session is None
    sess = _new_catalog_session(timeout=45) if own_sess else session
    buckets = defaultdict(list)
    selcols = "designation,source_id,ra,dec,pmra,pmdec,class_1,yso_pub,stype_ml,stype_ml_prob1,varclassgaia"
    try:
        for field_name, objstr, radius in fields:
            with sess.get(
                safe_url,
                params={
                    "catalog": "splices",
                    "spatial": "cone",
                    "objstr": objstr,
                    "radius": radius,
                    "outfmt": "1",
                    "selcols": selcols,
                },
                timeout=45,
                allow_redirects=False,
            ) as resp:
                resp.raise_for_status()
                rows = parse_ipac_ascii_table(resp.text)

            for row in rows:
                ml_class, subclass, grade = _classify_splices_row(row)
                if ml_class is None or len(buckets[ml_class]) >= per_class_cap:
                    continue
                ra = _safe_float(row.get("ra"))
                dec = _safe_float(row.get("dec"))
                if ra is None or dec is None or not (0.0 <= ra <= 360.0 and -90.0 <= dec <= 90.0):
                    continue
                sid = row.get("source_id") or row.get("designation")
                if not sid:
                    continue
                buckets[ml_class].append({
                    "target_name": _sanitize_target_name(f"SPLICES_{field_name}_{sid}"),
                    "ra_deg": round(ra, 6),
                    "dec_deg": round(dec, 6),
                    "pmra": round(_safe_float(row.get("pmra"), 0.0), 4),
                    "pmdec": round(_safe_float(row.get("pmdec"), 0.0), 4),
                    "ref_epoch": 2016.0 if row.get("source_id") else 2000.0,
                    "ml_class": ml_class,
                    "subclass": subclass,
                    "label_source": f"IRSA_SPLICES_v8.6:{field_name}",
                    "label_grade": grade,
                    "source_id": str(sid),
                })
    finally:
        if own_sess:
            sess.close()
    return [item for rows in buckets.values() for item in rows]


def _gaia_tap_queries(per_class_cap=300):
    cap = max(1, int(per_class_cap))
    return (
        (
            "Active galaxy or quasar",
            "QSO",
            "ESA_GaiaDR3_qso_candidates",
            "gold",
            f"""
            SELECT TOP {cap}
                q.source_id, g.ra, g.dec, g.pmra, g.pmdec, g.phot_g_mean_mag, q.redshift_qsoc
            FROM gaiadr3.qso_candidates AS q
            JOIN gaiadr3.gaia_source AS g USING (source_id)
            WHERE q.vari_best_class_name = 'AGN'
              AND g.classprob_dsc_combmod_quasar > 0.95
            """,
        ),
        (
            "Galaxy",
            "Galaxy_cand",
            "ESA_GaiaDR3_galaxy_candidates",
            "silver",
            f"""
            SELECT TOP {cap}
                g.source_id, g.ra, g.dec, g.pmra, g.pmdec, g.phot_g_mean_mag
            FROM gaiadr3.galaxy_candidates AS c
            JOIN gaiadr3.gaia_source AS g USING (source_id)
            WHERE g.classprob_dsc_combmod_galaxy > 0.95
              AND g.phot_g_mean_mag < 18.5
            """,
        ),
        (
            "Young star with ice or dust",
            "YSO_vari",
            "ESA_GaiaDR3_vari_YSO",
            "silver",
            f"""
            SELECT TOP {cap}
                v.source_id, g.ra, g.dec, g.pmra, g.pmdec, g.phot_g_mean_mag, v.best_class_score
            FROM gaiadr3.vari_classifier_result AS v
            JOIN gaiadr3.gaia_source AS g USING (source_id)
            WHERE v.best_class_name = 'YSO'
              AND v.best_class_score > 0.92
              AND g.phot_g_mean_mag < 17
            """,
        ),
        (
            "Evolved giant star",
            "LPV_vari",
            "ESA_GaiaDR3_vari_LPV",
            "silver",
            f"""
            SELECT TOP {cap}
                v.source_id, g.ra, g.dec, g.pmra, g.pmdec, g.phot_g_mean_mag, v.best_class_score
            FROM gaiadr3.vari_classifier_result AS v
            JOIN gaiadr3.gaia_source AS g USING (source_id)
            WHERE v.best_class_name = 'LPV'
              AND v.best_class_score > 0.97
              AND g.phot_g_mean_mag < 14
            """,
        ),
        (
            "Star",
            "AFGKM_star",
            "ESA_GaiaDR3_gaia_source_NEP",
            "silver",
            f"""
            SELECT TOP {cap}
                source_id, ra, dec, pmra, pmdec, phot_g_mean_mag, teff_gspphot
            FROM gaiadr3.gaia_source
            WHERE 1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', 270.0, 66.5, 2.0))
              AND classprob_dsc_combmod_star > 0.995
              AND phot_g_mean_mag BETWEEN 9 AND 14
              AND ruwe < 1.2
              AND teff_gspphot IS NOT NULL
            """,
        ),
    )


def fetch_gaia_curated_targets(session=None, per_class_cap=300):
    """Fetch curated Gaia DR3 targets across QSO, Galaxy, YSO, LPV giant, and field Star classes."""
    safe_url = validate_remote_url(ESA_GAIA_TAP_SYNC_URL, allowed_hosts=ALLOWED_CATALOG_HOSTS)
    own_sess = session is None
    sess = _new_catalog_session(timeout=45) if own_sess else session
    out = []
    try:
        for ml_class, prefix, label_source, grade, adql in _gaia_tap_queries(per_class_cap=per_class_cap):
            with sess.post(
                safe_url,
                data={"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": adql},
                timeout=45,
                allow_redirects=False,
            ) as resp:
                resp.raise_for_status()
                rows = list(csv.DictReader(io.StringIO(resp.text)))
            for row in rows:
                ra = _safe_float(row.get("ra"))
                dec = _safe_float(row.get("dec"))
                sid = (row.get("source_id") or "").strip()
                if ra is None or dec is None or not sid or not (0.0 <= ra <= 360.0 and -90.0 <= dec <= 90.0):
                    continue
                teff = _safe_float(row.get("teff_gspphot"))
                z = _safe_float(row.get("redshift_qsoc"))
                if teff is not None:
                    sub = f"Teff_{int(round(teff))}K"
                elif z is not None:
                    sub = f"QSO_z{z:.2f}"
                else:
                    sub = prefix
                out.append({
                    "target_name": _sanitize_target_name(f"GAIA_{prefix}_{sid}"),
                    "ra_deg": round(ra, 6),
                    "dec_deg": round(dec, 6),
                    "pmra": round(_safe_float(row.get("pmra"), 0.0), 4),
                    "pmdec": round(_safe_float(row.get("pmdec"), 0.0), 4),
                    "ref_epoch": 2016.0,
                    "ml_class": ml_class,
                    "subclass": sub,
                    "label_source": label_source,
                    "label_grade": grade,
                    "source_id": sid,
                })
    finally:
        if own_sess:
            sess.close()
    return out


def _is_spatially_duplicate(ra_deg, dec_deg, grid, sep_deg):
    cell_ra = int(math.floor(ra_deg * 360.0))
    cell_dec = int(math.floor(dec_deg * 360.0))
    cos_dec = max(0.05, abs(math.cos(math.radians(dec_deg))))
    for dra in (-1, 0, 1):
        for ddec in (-1, 0, 1):
            for ex_ra, ex_dec in grid.get(((cell_ra + dra) % 129600, cell_dec + ddec), ()):
                d_ra = (ra_deg - ex_ra) % 360.0
                if d_ra > 180.0:
                    d_ra -= 360.0
                if math.hypot(d_ra * cos_dec, dec_deg - ex_dec) < sep_deg:
                    return True
    return False


def _interleave_balanced(per_class_rows, per_class):
    ordered_classes = [cls for cls in LEVEL1_CLASSES if per_class_rows.get(cls)]
    result = []
    for slot in range(per_class):
        for cls in ordered_classes:
            bucket = per_class_rows[cls]
            if slot < len(bucket):
                result.append(bucket[slot])
    return result


def build_curated_catalog(
    per_class=200,
    out_csv=DEFAULT_OUT_CSV,
    include_spiff=True,
    include_splices=True,
    include_gaia=True,
    min_sep_arcsec=10.0,
    session=None,
):
    """Assemble, deduplicate, and round-robin interleave curated multi-class ML targets into CSV."""
    if isinstance(per_class, bool) or not isinstance(per_class, int) or per_class < 1 or per_class > 5000:
        raise ValueError(f"per_class must be int in [1, 5000], got {per_class!r}")
    if isinstance(min_sep_arcsec, bool) or not math.isfinite(float(min_sep_arcsec)) or float(min_sep_arcsec) < 0.0:
        raise ValueError(f"min_sep_arcsec must be >= 0, got {min_sep_arcsec!r}")

    candidates = []
    source_cap = max(per_class * 2, 100)
    if include_spiff:
        candidates.extend(fetch_spiff_ultracool_dwarfs(session=session, max_rows=source_cap))
    if include_splices:
        candidates.extend(fetch_irsa_splices_targets(session=session, per_class_cap=source_cap))
    if include_gaia:
        candidates.extend(fetch_gaia_curated_targets(session=session, per_class_cap=source_cap))

    # Keep higher-grade labels first (gold before silver), then deduplicate spatially.
    grade_rank = {"gold": 0, "silver": 1}
    candidates.sort(key=lambda r: (grade_rank.get(r["label_grade"], 9), r["ml_class"], r["target_name"]))

    sep_deg = float(min_sep_arcsec) / 3600.0
    spatial_grid = defaultdict(list)
    seen_names = set()
    by_class = defaultdict(list)
    for row in candidates:
        cls = row["ml_class"]
        if len(by_class[cls]) >= per_class:
            continue
        name = row["target_name"]
        if name in seen_names or _is_spatially_duplicate(row["ra_deg"], row["dec_deg"], spatial_grid, sep_deg):
            continue
        seen_names.add(name)
        spatial_grid[(int(math.floor(row["ra_deg"] * 360.0)) % 129600, int(math.floor(row["dec_deg"] * 360.0)))].append(
            (row["ra_deg"], row["dec_deg"])
        )
        by_class[cls].append(row)

    interleaved = _interleave_balanced(by_class, per_class)
    if not interleaved:
        raise RuntimeError("No curated targets passed filtering")

    abs_out = os.path.abspath(out_csv)
    os.makedirs(os.path.dirname(abs_out), exist_ok=True)
    tmp_path = f"{abs_out}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
            writer.writeheader()
            writer.writerows(interleaved)
        os.replace(tmp_path, abs_out)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return {
        "out_csv": abs_out,
        "total_targets": len(interleaved),
        "class_counts": {cls: len(by_class[cls]) for cls in LEVEL1_CLASSES if by_class[cls]},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build curated multi-class ML target catalog CSV from SPIFF, IRSA SPLICES, and ESA Gaia DR3."
    )
    parser.add_argument("--per-class", type=int, default=200, help="Target count cap per Level-1 class (default: 200 -> ~1200 total).")
    parser.add_argument("--out-csv", default=DEFAULT_OUT_CSV, help="Output CSV path.")
    parser.add_argument("--min-sep-arcsec", type=float, default=10.0, help="Minimum angular separation for deduplication (default: 10.0).")
    parser.add_argument("--no-spiff", action="store_true", help="Skip Zenodo SPIFF ultracool dwarf fetch.")
    parser.add_argument("--no-splices", action="store_true", help="Skip IRSA SPLICES Gator cones.")
    parser.add_argument("--no-gaia", action="store_true", help="Skip ESA Gaia DR3 TAP queries.")
    args = parser.parse_args(argv)

    summary = build_curated_catalog(
        per_class=args.per_class,
        out_csv=args.out_csv,
        include_spiff=not args.no_spiff,
        include_splices=not args.no_splices,
        include_gaia=not args.no_gaia,
        min_sep_arcsec=args.min_sep_arcsec,
    )
    print(f"Wrote {summary['total_targets']} curated targets to {summary['out_csv']}")
    for cls, count in summary["class_counts"].items():
        print(f"  - {cls}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
