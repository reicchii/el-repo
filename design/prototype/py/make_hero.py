"""Build a wide false-colour composite of a real SPHEREx field for the hero image.

    python py/make_hero.py barnard --dets 1,3,6 --size 640 --scale 6.15

Blue, green, red = the three detectors in wavelength order. One visit per detector
(the one with most frames), ZODI subtracted, rejected bits at zero weight, per-frame
median removed, frames reprojected to one TAN grid and median-stacked.
Writes data/hero_<target>.jpg and data/hero_<target>.json.
"""

import argparse
import json
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning
from PIL import Image
from reproject import reproject_interp

warnings.simplefilter("ignore", FITSFixedWarning)
warnings.simplefilter("ignore", RuntimeWarning)

S3 = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/"
REJECT = sum(1 << b for b in [0, 2, 6, 7, 9, 10, 11, 14, 15, 17, 20, 25, 26, 27, 28, 29])

ap = argparse.ArgumentParser()
ap.add_argument("target")
ap.add_argument("--dets", default="1,3,6")
ap.add_argument("--size", type=int, default=640)
ap.add_argument("--scale", type=float, default=6.15)
ap.add_argument("--max-frames", type=int, default=14)
args = ap.parse_args()

meta = json.load(open("data/targets.json"))["targets"][args.target]
cat = meta["catalogue"]
dets = [int(d) for d in args.dets.split(",")]
years = (61100 - 51544.5) / 365.25
cra = cat["ra"] + (cat["pmra"] or 0) / 1000 * years / 3600 / np.cos(np.radians(cat["dec"]))
cdec = cat["dec"] + (cat["pmdec"] or 0) / 1000 * years / 3600

grid = WCS(naxis=2)
grid.wcs.ctype = ["RA---TAN", "DEC--TAN"]
grid.wcs.crval = [cra, cdec]
grid.wcs.crpix = [(args.size + 1) / 2] * 2
grid.wcs.cdelt = [-args.scale / 3600, args.scale / 3600]
shape = (args.size, args.size)


def visits_of(frames):
    out, cur, last = [], None, None
    for f in sorted(frames, key=lambda f: f["mjd"]):
        if last is None or f["mjd"] - last > 30:
            cur = []
            out.append(cur)
        cur.append(f)
        last = f["mjd"]
    return out


def cut(f):
    key = f["uri"].split("ibe/data/spherex/", 1)[1]
    for attempt in range(3):
        try:
            with fits.open(S3 + key, use_fsspec=True, fsspec_kwargs={"block_size": 1 << 18}) as h:
                hdr = h["IMAGE"].header
                w = WCS(hdr)
                x, y = w.all_world2pix([[cra, cdec]], 0)[0]
                half = int(args.size * args.scale / 6.15 * 0.75)
                ny, nx = hdr["NAXIS2"], hdr["NAXIS1"]
                x0, x1 = max(int(x) - half, 0), min(int(x) + half, nx)
                y0, y1 = max(int(y) - half, 0), min(int(y) + half, ny)
                if x1 - x0 < 50 or y1 - y0 < 50:
                    return None
                img = h["IMAGE"].section[y0:y1, x0:x1].astype("f8") - h["ZODI"].section[y0:y1, x0:x1].astype("f8")
                flg = h["FLAGS"].section[y0:y1, x0:x1].astype("i8")
                img[(flg & REJECT) != 0] = np.nan
                img -= np.nanmedian(img)
                out, foot = reproject_interp((img, w[y0:y1, x0:x1]), grid, shape_out=shape)
                out[foot < 0.5] = np.nan
                return out.astype("f4")
        except Exception:
            time.sleep(1 + attempt)
    return None


t0 = time.time()
channels, info = [], []
for d in dets:
    vis = visits_of([f for f in meta["frames"] if f["det"] == d])
    best = max(vis, key=len)
    use = best[: args.max_frames]
    with ThreadPoolExecutor(12) as pool:
        cubes = [c for c in pool.map(cut, use) if c is not None]
    stack = np.nanmedian(np.stack(cubes), axis=0)
    channels.append(stack)
    info.append({"det": d, "frames": len(cubes), "mjd_first": use[0]["mjd"], "mjd_last": use[-1]["mjd"]})
    print(f"D{d}: {len(cubes)} frames in {time.time() - t0:.0f} s")


def stretch(a):
    v = a[np.isfinite(a)]
    lo = np.percentile(v, 30)
    hi = np.percentile(v, 99.85)
    t = np.clip((a - lo) / (hi - lo), 0, None)
    out = np.clip(np.arcsinh(t * 12) / np.arcsinh(12), 0, 1)
    # flagged cores of bright stars are saturated: fill holes that sit inside bright light with full brightness
    hole = ~np.isfinite(out)
    filled = np.nan_to_num(out, nan=0.0)
    near = np.zeros_like(filled)
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            near = np.maximum(near, np.roll(np.roll(filled, dy, 0), dx, 1))
    filled[hole & (near > 0.55)] = 1.0
    return filled


rgb = np.dstack([stretch(channels[2]), stretch(channels[1]), stretch(channels[0])])
rgb = (np.flipud(rgb) * 255).astype("uint8")  # north up
Image.fromarray(rgb).save(f"data/hero_{args.target}.jpg", quality=84, optimize=True, progressive=True)
json.dump({"target": args.target, "size": args.size, "scale_arcsec": args.scale, "center": [cra, cdec],
           "fov_deg": args.size * args.scale / 3600, "channels": info, "order": "red=D%d green=D%d blue=D%d" % (dets[2], dets[1], dets[0])},
          open(f"data/hero_{args.target}.json", "w"))
print("wrote", f"data/hero_{args.target}.jpg", f"{time.time() - t0:.0f} s")
