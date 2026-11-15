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
from collections import Counter, defaultdict
import csv
import io
import math
import os
import re
import sys
import time
import zipfile

from astropy import units as u
from astropy.coordinates import SkyCoord

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from phantom_worlds.contracts import HardenedHTTPSession, validate_remote_url
from phantom_worlds.real_ml_data import ang2pix_nest32

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
    ("Perseus", "52.0 +31.0", "2400"),
    ("Serpens", "277.5 +1.2", "2400"),
    ("Chamaeleon", "167.0 -77.0", "2400"),
    ("Cepheus", "315.0 +68.0", "2400"),
    ("MonR2", "91.9 -6.4", "1800"),
    ("Lupus", "238.0 -35.0", "2400"),
    ("IC348", "56.1 +32.2", "2400"),
    ("RCorA", "285.5 -37.0", "2400"),
)

HIGH_B_EXTRAGALACTIC_FIELDS = (
    ("NGP", 192.8, 27.1, 7.0),
    ("Bootes", 218.0, 34.0, 7.0),
    ("Lockman", 161.0, 58.0, 7.0),
    ("ElaisN1", 242.5, 54.5, 7.0),
    ("SGP", 12.9, -27.1, 7.0),
    ("Virgo", 187.7, 12.4, 7.0),
    ("Coma", 195.0, 28.0, 7.0),
    ("Fornax", 54.6, -35.4, 7.0),
    ("EGS", 214.8, 52.8, 7.0),
    ("ELAISS1", 9.5, -44.0, 7.0),
)

_LOCAL_GROUP_EXCLUSIONS = (
    (80.89, -69.75, 12.0),   # LMC
    (13.19, -72.83, 7.0),    # SMC
    (10.68, 41.27, 4.0),     # M31
    (23.46, 30.66, 2.0),     # M33
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


def _galactic_abs_b(ra_deg, dec_deg):
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    ra_p = math.radians(192.85948)
    dec_p = math.radians(27.12825)
    sin_b = math.sin(dec) * math.sin(dec_p) + math.cos(dec) * math.cos(dec_p) * math.cos(ra - ra_p)
    return abs(math.degrees(math.asin(max(-1.0, min(1.0, sin_b)))))


def _ang_sep_deg(ra1_deg, dec1_deg, ra2_deg, dec2_deg):
    r1, d1 = math.radians(ra1_deg), math.radians(dec1_deg)
    r2, d2 = math.radians(ra2_deg), math.radians(dec2_deg)
    s_d = math.sin(0.5 * (d2 - d1))
    s_r = math.sin(0.5 * (r2 - r1))
    a = min(1.0, max(0.0, s_d * s_d + math.cos(d1) * math.cos(d2) * s_r * s_r))
    return math.degrees(2.0 * math.asin(math.sqrt(a)))


def _is_outside_local_group(ra_deg, dec_deg):
    return all(_ang_sep_deg(ra_deg, dec_deg, lg_ra, lg_dec) >= lg_rad for lg_ra, lg_dec, lg_rad in _LOCAL_GROUP_EXCLUSIONS)


def fetch_irsa_splices_targets(session=None, fields=SPLICES_FIELDS, per_class_cap=300):
    """Query IRSA SPLICES via Gator cones for YSOs, AGB evolved giants, and MS stars across diverse clouds."""
    safe_url = validate_remote_url(IRSA_GATOR_URL, allowed_hosts=ALLOWED_CATALOG_HOSTS, allow_query=True)
    own_sess = session is None
    sess = _new_catalog_session(timeout=45) if own_sess else session
    field_buckets = defaultdict(lambda: defaultdict(list))
    selcols = "designation,source_id,ra,dec,pmra,pmdec,class_1,yso_pub,stype_ml,stype_ml_prob1,varclassgaia"
    per_field_cap = max(25, per_class_cap)
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

            is_survey_table = len(rows) > 10
            for row in rows:
                ml_class, subclass, grade = _classify_splices_row(row)
                if ml_class is None or len(field_buckets[ml_class][field_name]) >= per_field_cap:
                    continue
                ra = _safe_float(row.get("ra"))
                dec = _safe_float(row.get("dec"))
                if ra is None or dec is None or not (0.0 <= ra <= 360.0 and -90.0 <= dec <= 90.0):
                    continue
                abs_b = _galactic_abs_b(ra, dec)
                if is_survey_table and ml_class in ("Evolved giant star", "Star") and abs_b < 10.0:
                    continue
                sid = row.get("source_id") or row.get("designation")
                if not sid:
                    continue
                field_buckets[ml_class][field_name].append({
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
                    "_region": field_name,
                    "_abs_b": abs_b,
                    "_g_mag": None,
                })
    finally:
        if own_sess:
            sess.close()

    out = []
    field_names = [f[0] for f in fields]
    for ml_class, by_field in field_buckets.items():
        picked = []
        max_len = max((len(v) for v in by_field.values()), default=0)
        for slot in range(max_len):
            for fname in field_names:
                flist = by_field.get(fname, ())
                if slot < len(flist):
                    picked.append(flist[slot])
                    if len(picked) >= per_class_cap:
                        break
            if len(picked) >= per_class_cap:
                break
        out.extend(picked)
    return out


def _gaia_tap_queries(per_class_cap=300):
    cap = max(1, int(per_class_cap))
    cone_cap = max(60, min(200, cap // max(1, len(HIGH_B_EXTRAGALACTIC_FIELDS)) + 25))
    queries = [
        (
            "Active galaxy or quasar",
            "QSO_Bright",
            "ESA_GaiaDR3_qso_candidates",
            "gold",
            "allsky_bright",
            f"""
            SELECT TOP 2000
                source_id, ra, dec, pmra, pmdec, phot_g_mean_mag
            FROM gaiadr3.gaia_source
            WHERE phot_g_mean_mag < 16.8
              AND in_qso_candidates = 'T'
              AND classprob_dsc_combmod_quasar > 0.98
              AND (b > 25 OR b < -25)
              AND pmra BETWEEN -1.2 AND 1.2
              AND pmdec BETWEEN -1.2 AND 1.2
              AND astrometric_excess_noise < 1.5
            """,
        ),
    ]
    for fname, ra_c, dec_c, rad_deg in HIGH_B_EXTRAGALACTIC_FIELDS:
        queries.append((
            "Active galaxy or quasar",
            f"QSO_{fname}",
            "ESA_GaiaDR3_qso_candidates",
            "gold",
            fname,
            f"""
            SELECT TOP {cone_cap}
                source_id, ra, dec, pmra, pmdec, phot_g_mean_mag
            FROM gaiadr3.gaia_source
            WHERE 1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra_c}, {dec_c}, {rad_deg}))
              AND in_qso_candidates = 'T'
              AND classprob_dsc_combmod_quasar > 0.95
              AND phot_g_mean_mag < 17.8
              AND pmra BETWEEN -1.2 AND 1.2
              AND pmdec BETWEEN -1.2 AND 1.2
              AND astrometric_excess_noise < 1.5
            """,
        ))
        queries.append((
            "Galaxy",
            f"GAL_{fname}",
            "ESA_GaiaDR3_galaxy_candidates",
            "silver",
            fname,
            f"""
            SELECT TOP {cone_cap}
                source_id, ra, dec, pmra, pmdec, phot_g_mean_mag
            FROM gaiadr3.gaia_source
            WHERE 1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {ra_c}, {dec_c}, {rad_deg}))
              AND in_galaxy_candidates = 'T'
              AND classprob_dsc_combmod_galaxy > 0.95
              AND phot_g_mean_mag BETWEEN 14.0 AND 18.2
              AND (pmra IS NULL OR (pmra BETWEEN -2.0 AND 2.0 AND pmdec BETWEEN -2.0 AND 2.0))
            """,
        ))
    queries.extend([
        (
            "Young star with ice or dust",
            "YSO_vari",
            "ESA_GaiaDR3_vari_YSO",
            "silver",
            "Ophiuchus",
            f"""
            SELECT TOP {min(60, cap)}
                v.source_id, g.ra, g.dec, g.pmra, g.pmdec, g.phot_g_mean_mag, v.best_class_score
            FROM gaiadr3.vari_classifier_result AS v
            JOIN gaiadr3.gaia_source AS g USING (source_id)
            WHERE 1=CONTAINS(POINT('ICRS', g.ra, g.dec), CIRCLE('ICRS', 246.8, -24.4, 4.0))
              AND v.best_class_name = 'YSO'
              AND v.best_class_score > 0.92
              AND g.phot_g_mean_mag < 17
            """,
        ),
        (
            "Evolved giant star",
            "LPV_vari",
            "ESA_GaiaDR3_vari_LPV",
            "silver",
            "RCorA",
            f"""
            SELECT TOP {min(60, cap)}
                v.source_id, g.ra, g.dec, g.pmra, g.pmdec, g.phot_g_mean_mag, v.best_class_score
            FROM gaiadr3.vari_classifier_result AS v
            JOIN gaiadr3.gaia_source AS g USING (source_id)
            WHERE 1=CONTAINS(POINT('ICRS', g.ra, g.dec), CIRCLE('ICRS', 285.5, -37.0, 5.0))
              AND v.best_class_name = 'LPV'
              AND v.best_class_score > 0.97
              AND g.phot_g_mean_mag < 14
            """,
        ),
        (
            "Star",
            "AFGKM_star",
            "ESA_GaiaDR3_gaia_source_NEP",
            "silver",
            "NEP",
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
    ])
    return tuple(queries)


def _post_gaia_csv(sess, safe_url, query, timeout=60, retries=3, close_conn=False):
    """Execute Gaia TAP ADQL CSV query with bounded retries on transient disconnects/timeouts."""
    last_err = None
    for attempt in range(max(1, int(retries))):
        kwargs = {
            "data": {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": " ".join(query.split())},
            "timeout": timeout,
            "allow_redirects": False,
        }
        if close_conn:
            kwargs["headers"] = {"Connection": "close"}
        try:
            with sess.post(safe_url, **kwargs) as resp:
                resp.raise_for_status()
                return list(csv.DictReader(io.StringIO(resp.text)))
        except (TimeoutError, OSError) as exc:
            last_err = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last_err


def fetch_gaia_curated_targets(session=None, per_class_cap=300):
    """Fetch curated Gaia DR3 targets across QSO, Galaxy, YSO, LPV giant, and field Star classes."""
    safe_url = validate_remote_url(ESA_GAIA_TAP_SYNC_URL, allowed_hosts=ALLOWED_CATALOG_HOSTS)
    own_sess = session is None
    sess = _new_catalog_session(timeout=60) if own_sess else session
    out = []
    try:
        for ml_class, prefix, label_source, grade, region, adql in _gaia_tap_queries(per_class_cap=per_class_cap):
            is_vari = "vari_classifier_result" in adql
            try:
                rows = _post_gaia_csv(
                    sess,
                    safe_url,
                    adql,
                    timeout=(20 if is_vari else 60),
                    retries=(1 if is_vari else 3),
                    close_conn=own_sess,
                )
                if own_sess:
                    print(f"[gaia] {prefix}: {len(rows)} rows", flush=True)
                    time.sleep(0.2)
            except (TimeoutError, OSError):
                if is_vari:
                    if own_sess:
                        print(f"[gaia] {prefix}: skipped optional vari cone timeout", flush=True)
                    continue
                raise
            for row in rows:
                ra = _safe_float(row.get("ra"))
                dec = _safe_float(row.get("dec"))
                sid = (row.get("source_id") or "").strip()
                if ra is None or dec is None or not sid or not (0.0 <= ra <= 360.0 and -90.0 <= dec <= 90.0):
                    continue
                abs_b = _galactic_abs_b(ra, dec)
                if ml_class in ("Active galaxy or quasar", "Galaxy"):
                    if abs_b < 25.0 or not _is_outside_local_group(ra, dec):
                        continue
                elif ml_class == "Evolved giant star" and abs_b < 10.0:
                    continue
                g_mag = _safe_float(row.get("phot_g_mean_mag"))
                teff = _safe_float(row.get("teff_gspphot"))
                z = _safe_float(row.get("redshift_qsoc"))
                if teff is not None:
                    sub = f"Teff_{int(round(teff))}K"
                elif z is not None:
                    sub = f"QSO_z{z:.2f}"
                elif ml_class == "Active galaxy or quasar" and g_mag is not None:
                    sub = f"QSO_G{g_mag:.1f}"
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
                    "_region": region,
                    "_abs_b": abs_b,
                    "_g_mag": g_mag,
                })
    finally:
        if own_sess:
            sess.close()
    return out


def _filter_gaia_isolated_candidates(
    candidates,
    session=None,
    radius_arcsec=25.0,
    mag_margin=2.0,
    batch_size=25,
):
    """Reject candidates with contaminating Gaia neighbors inside 25 arcsec for clean 14 arcsec cube extraction."""
    if not candidates:
        return []
    safe_url = validate_remote_url(ESA_GAIA_TAP_SYNC_URL, allowed_hosts=ALLOWED_CATALOG_HOSTS)
    own_sess = session is None
    sess = _new_catalog_session(timeout=35) if own_sess else session
    rad_deg = float(radius_arcsec) / 3600.0
    isolated = []
    try:
        for start in range(0, len(candidates), batch_size):
            batch = candidates[start : start + batch_size]
            cond = " OR ".join(
                f"1=CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {c['ra_deg']:.6f}, {c['dec_deg']:.6f}, {rad_deg:.6f}))"
                for c in batch
            )
            query = f"SELECT source_id, ra, dec, phot_g_mean_mag FROM gaiadr3.gaia_source WHERE {cond}"
            nbs = []
            for nrow in _post_gaia_csv(sess, safe_url, query, timeout=45, retries=3, close_conn=own_sess):
                nra = _safe_float(nrow.get("ra"))
                ndec = _safe_float(nrow.get("dec"))
                ng = _safe_float(nrow.get("phot_g_mean_mag"))
                if nra is not None and ndec is not None and ng is not None:
                    nbs.append(((nrow.get("source_id") or "").strip(), nra, ndec, ng))
            if own_sess:
                time.sleep(0.15)
                if ((start // batch_size) + 1) % 10 == 0 or start + batch_size >= len(candidates):
                    print(f"[gaia-iso] checked {min(start + batch_size, len(candidates))}/{len(candidates)} -> kept {len(isolated)}", flush=True)
            for cand in batch:
                cra, cdec = cand["ra_deg"], cand["dec_deg"]
                csid = str(cand.get("source_id") or "").strip()
                hits = [
                    (nsid, nra, ndec, ng, _ang_sep_deg(cra, cdec, nra, ndec) * 3600.0)
                    for nsid, nra, ndec, ng in nbs
                ]
                hits = [h for h in hits if h[4] <= radius_arcsec]
                self_matches = [h for h in hits if (csid and h[0] == csid) or h[4] < 1.5]
                self_g = min((h[3] for h in self_matches), default=cand.get("_g_mag"))
                others = [h for h in hits if h not in self_matches]
                if self_g is None:
                    contaminated = any(h[3] < 15.5 for h in others)
                else:
                    contaminated = any(h[3] < (float(self_g) + float(mag_margin)) for h in others)
                if not contaminated:
                    isolated.append(cand)
    finally:
        if own_sess:
            sess.close()
    return isolated


def _prioritize_diverse_candidates(candidates, per_class):
    """Balance brightness strata and sky regions/cubes before deduplication and neighbor isolation."""
    by_class_raw = defaultdict(list)
    seen_class_sid = set()
    for r in candidates:
        sid = str(r.get("source_id") or "")
        cls_key = (r["ml_class"], sid) if sid else None
        if cls_key and cls_key in seen_class_sid:
            continue
        if cls_key:
            seen_class_sid.add(cls_key)
        row = dict(r)
        row["_ipix5"] = ang2pix_nest32(row["ra_deg"], row["dec_deg"])
        row.setdefault("_abs_b", _galactic_abs_b(row["ra_deg"], row["dec_deg"]))
        by_class_raw[row["ml_class"]].append(row)

    # Identify shared extragalactic ipix5 tiles and bright QSO density so cube extraction stays compact.
    qso_rows = by_class_raw.get("Active galaxy or quasar", [])
    gal_ipix_counts = Counter(r["_ipix5"] for r in by_class_raw.get("Galaxy", []))
    qso_ipix_counts = Counter(r["_ipix5"] for r in qso_rows)

    prioritized = []
    pool_cap = max(int(per_class * 1.8), 80)

    # Active galaxy or quasar: stratify G<16.0 (W2<=12), 16.0-16.8 (12<W2<=13), >=16.8 (13<W2<=14).
    if qso_rows:
        s_bright, s_med, s_faint = [], [], []
        for r in qso_rows:
            g = r.get("_g_mag")
            if g is not None and g < 16.0:
                s_bright.append(r)
            elif g is not None and g < 16.8:
                s_med.append(r)
            else:
                s_faint.append(r)
        s_bright.sort(key=lambda r: (-(qso_ipix_counts[r["_ipix5"]] + gal_ipix_counts[r["_ipix5"]]), r.get("_g_mag") or 99.0, r["target_name"]))
        s_med.sort(key=lambda r: (-(qso_ipix_counts[r["_ipix5"]] + gal_ipix_counts[r["_ipix5"]]), r.get("_g_mag") or 99.0, r["target_name"]))
        # Spread faint QSOs evenly across high-|b| survey regions while preferring Galaxy-overlapping cubes.
        faint_by_reg = defaultdict(list)
        for r in sorted(s_faint, key=lambda r: (-(gal_ipix_counts[r["_ipix5"]] > 0), -qso_ipix_counts[r["_ipix5"]], r.get("_g_mag") or 99.0, r["target_name"])):
            faint_by_reg[r.get("_region", "other")].append(r)
        faint_rr = []
        max_f = max((len(v) for v in faint_by_reg.values()), default=0)
        for slot in range(max_f):
            for reg in sorted(faint_by_reg.keys()):
                if slot < len(faint_by_reg[reg]):
                    faint_rr.append(faint_by_reg[reg][slot])
        # Interleave 35% bright / 35% medium / 30% cone QSOs so every W2 bin has clean representation.
        q_pool = []
        n_target = min(len(qso_rows), pool_cap)
        quotas = (int(0.35 * n_target), int(0.35 * n_target), n_target)
        buckets = ([s_bright, quotas[0]], [s_med, quotas[1]], [faint_rr, quotas[2]])
        idxs = [0, 0, 0]
        while len(q_pool) < n_target and any(idxs[k] < min(len(buckets[k][0]), buckets[k][1]) for k in range(3)):
            for k in range(3):
                arr, qcap = buckets[k]
                if idxs[k] < min(len(arr), qcap):
                    q_pool.append(arr[idxs[k]])
                    idxs[k] += 1
                    if len(q_pool) >= n_target:
                        break
        for arr in (s_bright, s_med, faint_rr):
            for r in arr:
                if len(q_pool) >= n_target:
                    break
                if r not in q_pool:
                    q_pool.append(r)
        prioritized.extend(q_pool)

    qso_chosen_ipix = Counter(r["_ipix5"] for r in prioritized if r["ml_class"] == "Active galaxy or quasar")

    for cls, rows in by_class_raw.items():
        if cls == "Active galaxy or quasar":
            continue
        if cls == "Galaxy":
            by_reg = defaultdict(list)
            for r in sorted(rows, key=lambda r: (-(qso_chosen_ipix[r["_ipix5"]] > 0), -gal_ipix_counts[r["_ipix5"]], r["target_name"])):
                by_reg[r.get("_region", "other")].append(r)
            max_g = max((len(v) for v in by_reg.values()), default=0)
            g_pool = []
            for slot in range(max_g):
                for reg in sorted(by_reg.keys()):
                    if slot < len(by_reg[reg]):
                        g_pool.append(by_reg[reg][slot])
            prioritized.extend(g_pool[:pool_cap])
        elif cls in ("Young star with ice or dust", "Evolved giant star"):
            grade_rank = {"gold": 0, "silver": 1}
            rows_sorted = sorted(rows, key=lambda r: (grade_rank.get(r["label_grade"], 9), -(r["_abs_b"] >= 10.0), r["target_name"]))
            by_reg = defaultdict(list)
            for r in rows_sorted:
                by_reg[r.get("_region", "other")].append(r)
            max_r = max((len(v) for v in by_reg.values()), default=0)
            c_pool = []
            for slot in range(max_r):
                for reg in sorted(by_reg.keys()):
                    if slot < len(by_reg[reg]):
                        c_pool.append(by_reg[reg][slot])
            prioritized.extend(c_pool[:pool_cap])
        else:
            grade_rank = {"gold": 0, "silver": 1}
            rows_sorted = sorted(rows, key=lambda r: (grade_rank.get(r["label_grade"], 9), r["target_name"]))
            prioritized.extend(rows_sorted[:pool_cap])

    return prioritized


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

    candidates = _prioritize_diverse_candidates(candidates, per_class=per_class)
    if include_gaia:
        check_classes = {"Young star with ice or dust", "Evolved giant star", "Active galaxy or quasar", "Galaxy"}
        to_check = [r for r in candidates if r["ml_class"] in check_classes]
        passthrough = [r for r in candidates if r["ml_class"] not in check_classes]
        candidates = passthrough + _filter_gaia_isolated_candidates(to_check, session=session)

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
        by_class[cls].append({k: row[k] for k in CSV_FIELDNAMES})

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
