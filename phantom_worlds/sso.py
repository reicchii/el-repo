"""IRSA Moving Object Search Tool (MOST) and Comet 3I/ATLAS SPHEREx query helpers."""

from datetime import datetime, timezone
import math
import re
import xml.etree.ElementTree as ET

import requests

from phantom_worlds.contracts import (
    ALLOWED_REMOTE_HOSTS,
    HardenedHTTPSession,
    validate_remote_url,
)

PIPELINE_VERSION = "1.0.0-hour0"
IRSA_MOST_URL = "https://irsa.ipac.caltech.edu/cgi-bin/MOST/nph-most"
COMET_3I_ATLAS_VOT_URL = "https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/obscore_3I_Atlas.vot"

_SSO_HOSTS = frozenset({"irsa.ipac.caltech.edu"})
_SSO_NAME_RE = re.compile(r"^[A-Za-z0-9 _./:+()-]{1,64}$")
_NAIF_ID_RE = re.compile(r"NAIF\s+ID=(\d+)")
_MAX_VOTABLE_BYTES = 8 * 1024 * 1024
_3I_ATLAS_ALIASES = frozenset(
    {
        "3I/ATLAS",
        "3I",
        "3I ATLAS",
        "C/2025 N1",
        "C/2025 N1 (ATLAS)",
        "COMET 3I/ATLAS",
    }
)


def _is_3i_atlas(cleaned_name):
    return cleaned_name.upper() in _3I_ATLAS_ALIASES


class SSOValidationError(ValueError):
    """Raised when an input moving-object name fails strict character/length validation."""


class SSONotFoundError(LookupError):
    """Raised when IRSA/Horizons cannot resolve the requested solar system object."""


class SSOUpstreamError(RuntimeError):
    """Raised when IRSA MOST or Comet 3I/ATLAS archive returns an error or invalid payload."""


def validate_sso_name(raw_name):
    """Validate and normalize a solar system target name before remote query."""
    if not isinstance(raw_name, str):
        raise SSOValidationError("Object name must be a string")
    cleaned = re.sub(r"\s+", " ", raw_name.strip())
    if not cleaned or len(cleaned) > 64 or ".." in cleaned or "\\" in cleaned:
        raise SSOValidationError("Invalid object name length or path tokens")
    if not _SSO_NAME_RE.fullmatch(cleaned):
        raise SSOValidationError("Object name contains unsupported characters")
    return cleaned


def _safe_archive_link(raw_url):
    if not isinstance(raw_url, str) or not raw_url.strip():
        return None
    candidate = raw_url.strip()
    if candidate.startswith("/"):
        candidate = f"https://irsa.ipac.caltech.edu{candidate}"
    try:
        return validate_remote_url(candidate, allowed_hosts=ALLOWED_REMOTE_HOSTS, allow_query=True)
    except ValueError:
        return None


def _parse_finite(val):
    if val is None or val == "":
        return None
    try:
        out = float(val)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _read_bounded_bytes(resp, max_bytes=_MAX_VOTABLE_BYTES):
    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise SSOUpstreamError(f"VOTable response exceeded {max_bytes} byte safety limit")
        chunks.append(chunk)
    return b"".join(chunks)


def parse_votable_rows(raw_bytes):
    """Parse an IVOA VOTable byte buffer into list[dict[str, str]] while rejecting DTD/entities."""
    head = raw_bytes[:16384].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise SSOUpstreamError("VOTable XML contains disallowed DTD or entity declarations")
    try:
        root = ET.fromstring(raw_bytes)
    except ET.ParseError as exc:
        raise SSOUpstreamError(f"Malformed VOTable XML from IRSA: {exc}") from exc

    table = None
    for elem in root.iter():
        if elem.tag.rsplit("}", 1)[-1] == "TABLE":
            table = elem
            break
    if table is None:
        return []

    fields = []
    rows = []
    for child in table:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "FIELD":
            fields.append(child.attrib.get("name") or child.attrib.get("ID") or f"col_{len(fields)}")
        elif tag == "DATA":
            for sub in child:
                if sub.tag.rsplit("}", 1)[-1] == "TABLEDATA":
                    for tr in sub:
                        if tr.tag.rsplit("}", 1)[-1] != "TR":
                            continue
                        tds = [td.text.strip() if td.text else "" for td in tr if td.tag.rsplit("}", 1)[-1] == "TD"]
                        row = {fields[i]: tds[i] if i < len(tds) else "" for i in range(len(fields))}
                        rows.append(row)
    return rows


def _extract_naif_candidates(err_text):
    """Order ambiguous Horizons NAIF IDs, preferring entries with a concrete designation."""
    preferred = []
    fallback = []
    seen = set()
    for line in err_text.splitlines():
        match = _NAIF_ID_RE.search(line)
        if not match:
            continue
        nid = match.group(1)
        if nid in seen:
            continue
        seen.add(nid)
        if "Designation=NO_VALUE" in line:
            fallback.append(nid)
        else:
            preferred.append(nid)
    return (preferred + fallback)[:4]


def _estimate_rate_arcsec_hr(track_points):
    if len(track_points) < 2:
        return None
    p0 = track_points[0]
    p1 = track_points[-1]
    dt_hr = (p1["mjd"] - p0["mjd"]) * 24.0
    if dt_hr <= 0.1:
        return None
    cos_dec = math.cos(math.radians(0.5 * (p0["dec_deg"] + p1["dec_deg"])))
    dra = ((p1["ra_deg"] - p0["ra_deg"] + 180.0) % 360.0 - 180.0) * cos_dec
    ddec = p1["dec_deg"] - p0["dec_deg"]
    return round(math.hypot(dra, ddec) * 3600.0 / dt_hr, 2)


def query_sso_spherex(name, session=None, frame_limit=120):
    """Query SPHEREx moving-object detections from IRSA MOST or the dedicated 3I/ATLAS VOTable."""
    cleaned = validate_sso_name(name)
    frame_limit = max(1, min(int(frame_limit), 500))
    owns_session = session is None
    sess = session if session is not None else HardenedHTTPSession(timeout=30, allowed_hosts=_SSO_HOSTS)

    normalized_frames = []
    disambiguated_naif_id = None
    query_mode = "irsa_most_spherex"
    source_url = IRSA_MOST_URL

    try:
        if _is_3i_atlas(cleaned):
            query_mode = "comet_3i_atlas_votable"
            source_url = COMET_3I_ATLAS_VOT_URL
            with sess.get(COMET_3I_ATLAS_VOT_URL, allow_redirects=False, stream=True, timeout=30) as resp:
                if resp.status_code != 200:
                    raise SSOUpstreamError(f"Comet 3I/ATLAS table returned HTTP {resp.status_code}")
                raw_bytes = _read_bounded_bytes(resp)
            raw_rows = parse_votable_rows(raw_bytes)
            for row in raw_rows:
                ra_obj = _parse_finite(row.get("comet_ra") or row.get("s_ra"))
                dec_obj = _parse_finite(row.get("comet_dec") or row.get("s_dec"))
                t_min = _parse_finite(row.get("t_min"))
                t_max = _parse_finite(row.get("t_max"))
                mjd = t_min if t_max is None else 0.5 * (t_min + t_max)
                if ra_obj is None or dec_obj is None or mjd is None:
                    continue
                em_min_m = _parse_finite(row.get("em_min"))
                em_max_m = _parse_finite(row.get("em_max"))
                normalized_frames.append(
                    {
                        "obs_id": row.get("obs_id", ""),
                        "detector": row.get("spherex_detector", ""),
                        "mjd": round(mjd, 5),
                        "ra_deg": round(ra_obj, 6),
                        "dec_deg": round(dec_obj, 6),
                        "field_ra_deg": _parse_finite(row.get("s_ra")),
                        "field_dec_deg": _parse_finite(row.get("s_dec")),
                        "em_min_um": round(em_min_m * 1e6, 3) if em_min_m is not None else None,
                        "em_max_um": round(em_max_m * 1e6, 3) if em_max_m is not None else None,
                        "sun_dist_au": None,
                        "geo_dist_au": None,
                        "phase_deg": None,
                        "vmag": None,
                        "exposure_s": _parse_finite(row.get("t_exptime")),
                        "uri": _safe_archive_link(row.get("access_url")),
                    }
                )
        else:
            params = {
                "catalog": "spherex",
                "input_type": "name_input",
                "obj_name": cleaned,
                "output_mode": "VOTable",
            }
            candidates = []
            with sess.get(IRSA_MOST_URL, params=params, allow_redirects=False, stream=True, timeout=30) as resp:
                if resp.status_code == 400:
                    err_text = _read_bounded_bytes(resp, max_bytes=262144).decode("utf-8", errors="replace")
                    candidates = _extract_naif_candidates(err_text)
                    if not candidates:
                        raise SSONotFoundError(f"IRSA MOST did not recognize object '{cleaned}'")
                elif resp.status_code != 200:
                    raise SSOUpstreamError(f"IRSA MOST returned HTTP {resp.status_code}")
                else:
                    raw_bytes = _read_bounded_bytes(resp)

            if candidates:
                resolved = False
                for nid in candidates:
                    params["obj_name"] = f"{nid}:NID"
                    with sess.get(IRSA_MOST_URL, params=params, allow_redirects=False, stream=True, timeout=30) as retry_resp:
                        if retry_resp.status_code == 200:
                            disambiguated_naif_id = nid
                            raw_bytes = _read_bounded_bytes(retry_resp)
                            resolved = True
                            break
                        if retry_resp.status_code != 400:
                            raise SSOUpstreamError(f"IRSA MOST returned HTTP {retry_resp.status_code}")
                if not resolved:
                    raise SSONotFoundError(f"IRSA MOST could not resolve object '{cleaned}'")
            raw_rows = parse_votable_rows(raw_bytes)
            for row in raw_rows:
                ra_obj = _parse_finite(row.get("ra_obj"))
                dec_obj = _parse_finite(row.get("dec_obj"))
                mjd_s = _parse_finite(row.get("mjd_start"))
                mjd_e = _parse_finite(row.get("mjd_end"))
                mjd = mjd_s if mjd_e is None else 0.5 * (mjd_s + mjd_e)
                if ra_obj is None or dec_obj is None or mjd is None:
                    continue
                normalized_frames.append(
                    {
                        "obs_id": row.get("observationid", ""),
                        "detector": row.get("planeid") or row.get("instrument", ""),
                        "mjd": round(mjd, 5),
                        "ra_deg": round(ra_obj, 6),
                        "dec_deg": round(dec_obj, 6),
                        "field_ra_deg": _parse_finite(row.get("ra")),
                        "field_dec_deg": _parse_finite(row.get("dec")),
                        "em_min_um": None,
                        "em_max_um": None,
                        "sun_dist_au": _parse_finite(row.get("sun_dist")),
                        "geo_dist_au": _parse_finite(row.get("geo_dist")),
                        "phase_deg": _parse_finite(row.get("phase")),
                        "vmag": _parse_finite(row.get("vmag")),
                        "exposure_s": _parse_finite(row.get("exposure_time")),
                        "uri": _safe_archive_link(row.get("uri")),
                    }
                )
    except requests.RequestException as exc:
        raise SSOUpstreamError(f"Failed to query IRSA moving-object archive: {exc}") from exc
    finally:
        if owns_session:
            sess.close()

    normalized_frames.sort(key=lambda r: (r["mjd"], r["obs_id"]))
    track_points = [
        {"mjd": r["mjd"], "ra_deg": r["ra_deg"], "dec_deg": r["dec_deg"], "vmag": r["vmag"]}
        for r in normalized_frames
    ]

    mid = normalized_frames[len(normalized_frames) // 2] if normalized_frames else None
    step = max(1, (len(track_points) + 399) // 400) if len(track_points) > 400 else 1
    sampled_track = track_points[::step]
    if track_points and sampled_track[-1] is not track_points[-1]:
        sampled_track.append(track_points[-1])
    return {
        "object_name": "3I/ATLAS (C/2025 N1)" if query_mode == "comet_3i_atlas_votable" else cleaned,
        "query_mode": query_mode,
        "resolved_naif_id": disambiguated_naif_id,
        "source_url": source_url,
        "status": "OK" if normalized_frames else "EMPTY",
        "data_as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pipeline_version": PIPELINE_VERSION,
        "center_ra_deg": mid["ra_deg"] if mid else None,
        "center_dec_deg": mid["dec_deg"] if mid else None,
        "mjd_min": normalized_frames[0]["mjd"] if normalized_frames else None,
        "mjd_max": normalized_frames[-1]["mjd"] if normalized_frames else None,
        "estimated_rate_arcsec_hr": _estimate_rate_arcsec_hr(track_points),
        "total_frames": len(normalized_frames),
        "frames": normalized_frames[:frame_limit],
        "track_points": sampled_track,
    }
