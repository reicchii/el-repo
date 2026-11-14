"""Cut, align and stack real SPHEREx frames of one target, per detector and visit.

    python py/stack_target.py wise0855 [--size 128] [--scale 3.075]

Reads only the needed rows of each Level 2 file from the public S3 bucket.
Method follows docs/PROJECT-CONTEXT.md section 8, stages 2 to 4, in a simplified form:
ZODI subtracted, IRSA's rejected flag bits at zero weight (bit 21 kept), a local median
background removed, frames reprojected to one TAN grid and averaged with clipping.
Positions use proper motion only (parallax ignored, under 0.5 arcsec for these targets).

Writes data/<target>_stacks.json (float16 pixels as base64, frame list with wavelength at
the target, visits) and data/<target>_stacks.npz.
"""

import argparse
import base64
import json
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.time import Time
from astropy.wcs import WCS, FITSFixedWarning
from reproject import reproject_interp

warnings.simplefilter("ignore", FITSFixedWarning)
warnings.simplefilter("ignore", RuntimeWarning)

S3 = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/"
REJECT_BITS = [0, 2, 6, 7, 9, 10, 11, 14, 15, 17, 20, 25, 26, 27, 28, 29]
REJECT_MASK = sum(1 << b for b in REJECT_BITS)
OVERFLOW_BIT = 1 << 1

ap = argparse.ArgumentParser()
ap.add_argument("target")
ap.add_argument("--size", type=int, default=128)
ap.add_argument("--scale", type=float, default=3.075)
ap.add_argument("--box", type=int, default=72, help="native pixels read around the target")
ap.add_argument("--dets", default="1,2,3,4,5,6")
args = ap.parse_args()

meta = json.load(open("data/targets.json"))["targets"][args.target]
cat = meta["catalogue"]
dets = {int(x) for x in args.dets.split(",")}
frames = sorted([f for f in meta["frames"] if f["det"] in dets], key=lambda f: f["mjd"])

# Visits: a gap over 30 days starts a new visit (section 8, stage 1)
visit, last = 0, None
for f in frames:
    if last is not None and f["mjd"] - last > 30:
        visit += 1
    f["visit"] = visit + 1
    last = f["mjd"]
n_visits = visit + 1


def present(mjd):
    """Catalogue position (epoch J2000 in SIMBAD) moved by proper motion to the date."""
    years = (mjd - 51544.5) / 365.25
    ra = cat["ra"] + (cat["pmra"] or 0) / 1000 * years / 3600 / np.cos(np.radians(cat["dec"]))
    dec = cat["dec"] + (cat["pmdec"] or 0) / 1000 * years / 3600
    return ra, dec


# Grid: centred between the entered position and the present one, so both marks fit
mid_mjd = Time("2026-01-01").mjd
pra, pdec = present(mid_mjd)
if meta.get("challenge_position"):
    from astropy.coordinates import SkyCoord
    import astropy.units as u

    c = SkyCoord(meta["challenge_position"], unit=(u.hourangle, u.deg))
    era, edec = c.ra.deg, c.dec.deg
else:
    era, edec = cat["ra"], cat["dec"]
cra, cdec = (era + pra) / 2, (edec + pdec) / 2

grid = WCS(naxis=2)
grid.wcs.ctype = ["RA---TAN", "DEC--TAN"]
grid.wcs.crval = [cra, cdec]
grid.wcs.crpix = [(args.size + 1) / 2, (args.size + 1) / 2]
grid.wcs.cdelt = [-args.scale / 3600, args.scale / 3600]
shape = (args.size, args.size)


def process(f):
    key = f["uri"].split("ibe/data/spherex/", 1)[1]
    for attempt in range(3):
        try:
            with fits.open(S3 + key, use_fsspec=True, fsspec_kwargs={"block_size": 1 << 16}) as h:
                hdr = h["IMAGE"].header
                w = WCS(hdr)
                tra, tdec = present(hdr["MJD-AVG"])
                x, y = w.all_world2pix([[tra, tdec]], 0)[0]
                ny, nx = hdr["NAXIS2"], hdr["NAXIS1"]
                if not (0 <= x < nx and 0 <= y < ny):
                    return {**f, "status": "outside"}
                half = args.box // 2
                x0, x1 = max(int(x) - half, 0), min(int(x) + half, nx)
                y0, y1 = max(int(y) - half, 0), min(int(y) + half, ny)
                img = h["IMAGE"].section[y0:y1, x0:x1].astype("f8")
                flg = h["FLAGS"].section[y0:y1, x0:x1].astype("i8")
                zod = h["ZODI"].section[y0:y1, x0:x1].astype("f8")
                ws = WCS(hdr, fobj=h, key="W")
                ws.sip = None
                wl, bw = ws.wcs_pix2world([[x, y]], 0)[0]
                xi, yi = int(round(x)), int(round(y))
                core = flg[max(yi - y0 - 1, 0): yi - y0 + 2, max(xi - x0 - 1, 0): xi - x0 + 2]
                data = img - zod
                data[(flg & REJECT_MASK) != 0] = np.nan
                data -= np.nanmedian(data)
                wcut = w[y0:y1, x0:x1]
                out, foot = reproject_interp((data, wcut), grid, shape_out=shape)
                out[foot < 0.5] = np.nan
                return {
                    **f,
                    "status": "ok",
                    "key": key,
                    "mjd_avg": hdr["MJD-AVG"],
                    "date_obs": hdr["DATE-OBS"],
                    "file_version": h[0].header.get("VERSION"),
                    "wave_um": float(wl),
                    "bw_um": float(bw),
                    "flag_frac": float(np.mean((flg & REJECT_MASK) != 0)),
                    "overflow_at_target": bool(np.any(core & OVERFLOW_BIT)),
                    "pix": out.astype("f4"),
                }
        except Exception as e:  # network hiccups: retry, then report
            err = f"{type(e).__name__}: {e}"
            time.sleep(1 + attempt)
    return {**f, "status": "error", "error": err[:200]}


t0 = time.time()
with ThreadPoolExecutor(16) as pool:
    results = list(pool.map(process, frames))
ok = [r for r in results if r["status"] == "ok"]
print(f"{args.target}: {len(ok)} of {len(frames)} frames cut in {time.time() - t0:.0f} s; "
      f"outside={sum(r['status'] == 'outside' for r in results)} errors={sum(r['status'] == 'error' for r in results)}")
for r in results:
    if r["status"] == "error":
        print("  error", r["uri"][-60:], r["error"])
        break

stacks, arrays = [], {}
for det in sorted(dets):
    for v in range(1, n_visits + 1):
        sel = [r for r in ok if r["det"] == det and r["visit"] == v]
        if not sel:
            continue
        cube = np.stack([r["pix"] for r in sel])
        if len(sel) >= 3:
            mean, med, std = sigma_clipped_stats(cube, axis=0, sigma=3.0)
            img = np.asarray(mean)
        else:
            img = np.nanmean(cube, axis=0)
        n_good = np.sum(np.isfinite(cube), axis=0)
        _, bg, noise = sigma_clipped_stats(img[np.isfinite(img)], sigma=3.0)
        img = img - bg
        sid = f"d{det}v{v}"
        arrays[sid] = img.astype("f4")
        mjds = [r["mjd_avg"] for r in sel]
        stacks.append({
            "id": sid,
            "det": det,
            "visit": v,
            "n": len(sel),
            "mjd_first": min(mjds),
            "mjd_last": max(mjds),
            "wave_min_um": min(r["wave_um"] for r in sel),
            "wave_max_um": max(r["wave_um"] for r in sel),
            "noise": float(noise),
            "max_depth": int(n_good.max()),
            "pixels_f16_b64": base64.b64encode(img.astype("<f2").tobytes()).decode(),
        })

entered = grid.all_world2pix([[era, edec]], 0)[0].tolist()
present_by_visit = {}
for v in range(1, n_visits + 1):
    vm = [r["mjd_avg"] for r in ok if r["visit"] == v]
    if vm:
        m = float(np.mean(vm))
        present_by_visit[v] = {"mjd": m, "xy": grid.all_world2pix([list(present(m))], 0)[0].tolist(),
                               "radec": list(present(m))}

out = {
    "target": args.target,
    "made_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "method": __doc__.strip().splitlines()[0],
    "grid": {"size": args.size, "scale_arcsec": args.scale, "crval": [cra, cdec], "projection": "TAN"},
    "entered": {"radec": [era, edec], "xy": entered, "source": meta.get("challenge_position") or "catalogue"},
    "present_by_visit": present_by_visit,
    "visits": n_visits,
    "frames": [{k: r[k] for k in ("obsid", "det", "visit", "mjd_avg", "date_obs", "wave_um", "bw_um",
                                  "flag_frac", "overflow_at_target", "release", "file_version", "key")}
               for r in ok],
    "stacks": stacks,
}
json.dump(out, open(f"data/{args.target}_stacks.json", "w"))
np.savez_compressed(f"data/{args.target}_stacks.npz", **arrays)
print("stacks:", ", ".join(f"{s['id']}(n={s['n']})" for s in stacks))
