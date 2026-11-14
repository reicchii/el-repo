"""Fetch real catalogue facts (CDS Sesame) and SPHEREx frame lists (IRSA TAP) for the five test targets.

Writes data/targets.json. Every value carries its source.
"""

import csv
import io
import json
import time
import urllib.parse
import xml.etree.ElementTree as ET

import requests

OUT = "data/targets.json"
TARGETS = [
    ("barnard", "Barnard's Star", "Barnard's Star"),
    ("epsindib", "Epsilon Indi B", "eps Ind B"),
    ("wise0855", "WISE 0855", "WISE J085510.83-071442.5"),
    ("rwaur", "RW Aurigae", "RW Aur"),
    ("rdra", "R Draconis", "R Dra"),
]
# The challenge page's own string for WISE 0855 (docs/PROJECT-CONTEXT.md section 2)
CHALLENGE_POS = {"wise0855": "08h55m10.831s -7d14m42.53s"}


def sesame(name):
    url = "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/S?" + urllib.parse.quote(name)
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    res = root.find(".//Resolver")
    if res is None:
        raise RuntimeError(f"Sesame found nothing for {name}")

    def txt(path):
        el = res.find(path)
        return el.text if el is not None else None

    def num(path):
        v = txt(path)
        return float(v) if v not in (None, "") else None

    return {
        "resolver": res.get("name"),
        "oname": txt("oname"),
        "otype": txt("otype"),
        "sptype": txt("spType"),
        "ra": num("jradeg"),
        "dec": num("jdedeg"),
        "pos_ref": txt("refPos"),
        "pmra": num("pm/pmRA"),
        "pmdec": num("pm/pmDE"),
        "pm_ref": txt("pm/r"),
        "plx": num("plx/v"),
        "plx_err": num("plx/e"),
        "plx_ref": txt("plx/r"),
        "resolved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def frames(ra, dec):
    q = (
        "SELECT a.uri, p.obsid, p.energy_bandpassname, p.time_bounds_lower, p.time_bounds_upper, "
        "p.energy_bounds_lower, p.energy_bounds_upper, p.datarelease, p.provenance_version "
        "FROM spherex.artifact a JOIN spherex.plane p ON a.planeid = p.planeid "
        f"WHERE 1 = CONTAINS(POINT('ICRS', {ra}, {dec}), p.poly)"
    )
    r = requests.post(
        "https://irsa.ipac.caltech.edu/TAP/sync",
        data={"QUERY": q, "LANG": "ADQL", "FORMAT": "csv"},
        timeout=300,
    )
    r.raise_for_status()
    return list(csv.DictReader(io.StringIO(r.text))), q


out = {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "targets": {}}
for tid, title, query_name in TARGETS:
    cat = sesame(query_name)
    rows, q = frames(cat["ra"], cat["dec"])
    out["targets"][tid] = {
        "id": tid,
        "title": title,
        "sesame_query": query_name,
        "catalogue": cat,
        "challenge_position": CHALLENGE_POS.get(tid),
        "tap_query": q,
        "frames": [
            {
                "uri": r["uri"],
                "obsid": r["obsid"],
                "det": int(r["energy_bandpassname"].split("-D")[-1]),
                "mjd": float(r["time_bounds_lower"]),
                "mjd_end": float(r["time_bounds_upper"]),
                "wmin_um": float(r["energy_bounds_lower"]) * 1e6,
                "wmax_um": float(r["energy_bounds_upper"]) * 1e6,
                "release": r["datarelease"],
                "version": r["provenance_version"],
            }
            for r in rows
        ],
    }
    print(f"{tid:9s} {cat['oname']!s:28s} {cat['otype']!s:6s} frames={len(rows)}")

with open(OUT, "w") as f:
    json.dump(out, f, indent=1)
print("wrote", OUT)
