"""Assemble the prototype page from the template and the fetched data.

    python py/build.py ../../docs/PROJECT-CONTEXT.md phantom-worlds.html

Real data: catalogue facts (Sesame), frame lists (IRSA TAP), stacks (S3 byte ranges),
Gaia DR3 overlay (IRSA TAP), pass marks and limits (PROJECT-CONTEXT.md section 13).
"""

import csv
import io
import json
import os
import re
import sys

import numpy as np
import requests
from astropy.wcs import WCS

ctx_path, out_path = sys.argv[1], sys.argv[2]
ORDER = ["wise0855", "barnard", "epsindib", "rwaur", "rdra"]
meta = json.load(open("data/targets.json"))


def gaia_in_grid(st):
    g = st["grid"]
    w = WCS(naxis=2)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = g["crval"]
    w.wcs.crpix = [(g["size"] + 1) / 2] * 2
    w.wcs.cdelt = [-g["scale_arcsec"] / 3600, g["scale_arcsec"] / 3600]
    r = g["size"] * g["scale_arcsec"] / 3600 * 0.72
    q = (f"SELECT ra, dec, pmra, pmdec, phot_g_mean_mag FROM gaia_dr3_source WHERE "
         f"1=CONTAINS(POINT('ICRS',ra,dec), CIRCLE('ICRS',{g['crval'][0]},{g['crval'][1]},{r})) AND phot_g_mean_mag < 18.5")
    resp = requests.post("https://irsa.ipac.caltech.edu/TAP/sync", data={"QUERY": q, "LANG": "ADQL", "FORMAT": "csv"}, timeout=300)
    resp.raise_for_status()
    out = []
    for s in csv.DictReader(io.StringIO(resp.text)):
        x, y = w.all_world2pix([[float(s["ra"]), float(s["dec"])]], 0)[0]
        if -2 <= x <= g["size"] + 1 and -2 <= y <= g["size"] + 1:
            num = lambda k: float(s[k]) if s[k] not in ("", None) else 0.0
            out.append({"x": round(float(x), 2), "y": round(float(y), 2), "pmra": num("pmra"), "pmdec": num("pmdec"), "g": round(num("phot_g_mean_mag"), 2)})
    return out


targets = {}
for tid in ORDER:
    t = meta["targets"][tid]
    st_path = f"data/{tid}_stacks.json"
    st = json.load(open(st_path)) if os.path.exists(st_path) else None
    wave = {}
    if st:
        for f in st["frames"]:
            wave[(f["obsid"], f["det"])] = round(f["wave_um"], 4)
    frames = [[round(f["mjd"], 4), f["det"], wave.get((f["obsid"], f["det"]))] for f in t["frames"]]
    entry = {k: t[k] for k in ("title", "sesame_query", "catalogue", "challenge_position")}
    entry["frames"] = frames
    if st:
        st_out = {k: st[k] for k in ("grid", "entered", "present_by_visit", "visits")}
        st_out["stacks"] = [{**{k: s[k] for k in ("id", "det", "visit", "n", "mjd_first", "mjd_last", "wave_min_um", "wave_max_um", "noise")}, "b64": s["pixels_f16_b64"]} for s in st["stacks"]]
        st_out["gaia"] = gaia_in_grid(st)
        entry["stacks"] = st_out
        print(f"{tid}: {len(frames)} frames, {len(st_out['stacks'])} stacks, {len(st_out['gaia'])} Gaia stars")
    else:
        entry["stacks"] = None
        print(f"{tid}: {len(frames)} frames, no stacks")
    targets[tid] = entry

# Proof tables straight from the plan, so the page cannot drift from it
ctx = open(ctx_path, encoding="utf-8").read()


def table_rows(heading):
    sec = ctx.split(heading, 1)[1].split("\n### ", 1)[0]
    rows = []
    for line in sec.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and re.match(r"^[AB]\d+$", cells[0]):
            rows.append(cells)
    return rows


tierA, tierB = table_rows("### 13.2 Tier A tests"), table_rows("### 13.3 Tier B tests")
credits = ctx.split("### 13.5 Credits to show", 1)[1].split("\n---", 1)[0].strip()
credits = re.sub(r"\s*DOIs are in[^.]*\.", "", re.sub(r"`[^`]*`", "", credits)).replace("  ", " ").strip()

findings = {}
if os.path.exists("data/wise0855_stacks.npz"):
    d = json.load(open("data/wise0855_stacks.json"))
    a = np.load("data/wise0855_stacks.npz")
    d6 = []
    for v in (2, 3):
        s = next(s for s in d["stacks"] if s["id"] == f"d6v{v}")
        x, y = d["present_by_visit"][str(v)]["xy"]
        xi, yi = int(round(x)), int(round(y))
        d6.append(float(np.nanmax(a[s["id"]][yi - 2:yi + 3, xi - 2:xi + 3]) / s["noise"]))
    findings["wise0855"] = {"d6": d6, "sep_arcsec": 4.6}

data = {
    "fetched_at": meta["fetched_at"],
    "order": ORDER,
    "targets": targets,
    "findings": findings,
    "proof": {
        "tierA": tierA,
        "tierB": tierB,
        "limits": [
            "SPHEREx reaches 17.8 to 18.8 AB magnitude at 3.8 to 5.0 µm after four surveys (Bock et al. 2025). Our depth per field comes from test B8.",
            "Crowding costs about 1.5 magnitudes near the Galactic plane (SMDET-1 paper, arXiv 2608.00046). Our measured loss comes from tests B2 and B8.",
            "Planet X: the faintest moving test object we recover, the motion range tested and the field size limit. Generated from test B8.",
            "Class percentages are calibrated on our test fields only. A class is a suggestion for follow-up. It confirms nothing.",
            "Molecule readings are feature strengths. Composition percentages are shown only for ice relative to water ice.",
            "How much of a type the molecule readings alone reveal comes from test B13.",
        ],
        "next": [
            "Frame packs for the five targets, read by byte range and aligned to Gaia DR3 (T04 to T07).",
            "Live mode for any position through the API (T13).",
            "Spectrum on the fly and molecule readings with errors (T10, T43c).",
            "Type estimates from the calibrated classifier, published only if it passes its release gate (T43e, T43f).",
            "Remove known, Search by light and cases in two processed fields (T40 to T47).",
            "Accounts, blind review and forecasts (Tier C).",
        ],
        "credits": credits,
    },
}

tpl = open("template.html", encoding="utf-8").read()
blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
html = tpl.replace("/*__DATA__*/", blob)
open(out_path, "w", encoding="utf-8").write(html)
print(f"tier A {len(tierA)} tests, tier B {len(tierB)} tests; wrote {out_path} ({len(html) / 1e6:.2f} MB)")
